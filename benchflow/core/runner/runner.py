"""Threaded benchmark runner with multi-iteration experiment support.

Key features:
- Barrier-synchronized thread startup with high-resolution timing
- Multi-iteration experiments with configurable pause between iterations
- Setup/teardown query execution with per-iteration isolation
- Time-series capture in 1-second windows
- Seed control for reproducible parameter generation
- HDR histogram per thread for O(1) record, O(buckets) merge
"""

from __future__ import annotations

import gc
import logging
import random
import threading
import time
from dataclasses import dataclass, field

from benchflow.core.metrics.aggregator import (
    build_step_result_from_histogram,
    compute_cross_iteration_aggregate,
)
from benchflow.core.metrics.histogram import HdrHistogram
from benchflow.core.result import (
    AggregateTargetResult,
    BenchFlowInfo,
    DatabaseInfo,
    EnvironmentInfo,
    ErrorInfo,
    ErrorSample,
    IterationResult,
    LatencySummary,
    RunResult,
    ScenarioRef,
    StackInfo,
    StepResult,
    TargetResult,
    TimeWindow,
    compute_scenario_signature,
)
from benchflow.core.scenario.schema import Scenario, Step, TargetConfig
from benchflow.workers.protocol import Worker, get_worker_factory

# Lazy import to avoid circular deps — used only when external targets are present
_run_external_target = None


def _get_external_runner():  # noqa: ANN202
    global _run_external_target
    if _run_external_target is None:
        from benchflow.workers.external.subprocess_worker import (
            run_external_target as _fn,
        )
        _run_external_target = _fn
    return _run_external_target


def _is_external_target(target: TargetConfig) -> bool:
    """A target is external if its worker_config contains a 'command' key."""
    return "command" in target.worker_config

logger = logging.getLogger(__name__)

MAX_ERROR_SAMPLES = 50


# ---------------------------------------------------------------------------
# Per-thread data structures
# ---------------------------------------------------------------------------


@dataclass
class ThreadResult:
    step_histograms: dict[str, HdrHistogram] = field(default_factory=dict)
    step_latencies: dict[str, list[int]] = field(default_factory=dict)  # reservoir sample
    step_ops: dict[str, int] = field(default_factory=dict)
    step_errors: dict[str, int] = field(default_factory=dict)
    error_samples: list[ErrorSample] = field(default_factory=list)
    # Time-series: step_name -> second_offset -> list of latencies in that second
    step_time_buckets: dict[str, dict[int, list[int]]] = field(default_factory=dict)
    step_time_errors: dict[str, dict[int, int]] = field(default_factory=dict)


RESERVOIR_MAX = 10_000


def _worker_thread(
    worker: Worker,
    steps: list[Step],
    duration_s: int,
    barrier: threading.Barrier,
    result: ThreadResult,
    rng: random.Random | None = None,
) -> None:
    barrier.wait()

    start_ns = time.perf_counter_ns()
    deadline_ns = start_ns + duration_s * 1_000_000_000

    for step in steps:
        result.step_histograms[step.name] = HdrHistogram()
        result.step_latencies[step.name] = []
        result.step_ops[step.name] = 0
        result.step_errors[step.name] = 0
        result.step_time_buckets[step.name] = {}
        result.step_time_errors[step.name] = {}

    # Pre-compute reservoir threshold to avoid repeated dict lookups
    reservoir_max = RESERVOIR_MAX

    while time.perf_counter_ns() < deadline_ns:
        for step in steps:
            t0 = time.perf_counter_ns()
            try:
                worker.execute(step)
            except Exception as exc:
                elapsed_ns = time.perf_counter_ns() - start_ns
                second = int(elapsed_ns // 1_000_000_000)
                result.step_errors[step.name] += 1
                result.step_time_errors[step.name][second] = (
                    result.step_time_errors[step.name].get(second, 0) + 1
                )
                if len(result.error_samples) < MAX_ERROR_SAMPLES:
                    result.error_samples.append(ErrorSample(step=step.name, message=str(exc)))
                continue
            t1 = time.perf_counter_ns()
            latency = t1 - t0

            # Record into HDR histogram (O(1))
            result.step_histograms[step.name].record(latency)
            result.step_ops[step.name] += 1

            # Reservoir sampling for ECDF (bounded to RESERVOIR_MAX)
            sample_list = result.step_latencies[step.name]
            op_count = result.step_ops[step.name]
            if op_count <= reservoir_max:
                sample_list.append(latency)
            else:
                # Vitter's Algorithm R: replace with probability reservoir_max / op_count
                j = rng.randint(0, op_count - 1) if rng else random.randint(0, op_count - 1)
                if j < reservoir_max:
                    sample_list[j] = latency

            # Time-series bucketing
            elapsed_ns = t1 - start_ns
            second = int(elapsed_ns // 1_000_000_000)
            bucket = result.step_time_buckets[step.name]
            if second not in bucket:
                bucket[second] = []
            bucket[second].append(latency)


# ---------------------------------------------------------------------------
# Setup / teardown execution
# ---------------------------------------------------------------------------


def _execute_setup_queries(worker: Worker, queries: list[str]) -> None:
    """Execute setup queries sequentially using a single worker. Fail-fast."""
    for query in queries:
        logger.info("Executing setup query: %s", query[:80])
        worker.execute_raw(query)


def _execute_teardown_queries(worker: Worker, queries: list[str]) -> None:
    """Execute teardown queries sequentially. Log errors but don't fail."""
    for query in queries:
        try:
            logger.info("Executing teardown query: %s", query[:80])
            worker.execute_raw(query)
        except Exception as exc:
            logger.warning("Teardown query failed (continuing): %s — %s", query[:80], exc)


# ---------------------------------------------------------------------------
# Time-series aggregation
# ---------------------------------------------------------------------------


def _merge_time_series(
    thread_results: list[ThreadResult],
    step_name: str,
) -> list[TimeWindow]:
    """Merge per-thread time-series buckets into per-step TimeWindow list."""
    merged_buckets: dict[int, list[int]] = {}
    merged_errors: dict[int, int] = {}

    for tr in thread_results:
        for second, latencies in tr.step_time_buckets.get(step_name, {}).items():
            if second not in merged_buckets:
                merged_buckets[second] = []
            merged_buckets[second].extend(latencies)
        for second, errs in tr.step_time_errors.get(step_name, {}).items():
            merged_errors[second] = merged_errors.get(second, 0) + errs

    if not merged_buckets:
        return []

    windows: list[TimeWindow] = []
    max_second = max(merged_buckets.keys())

    for second in range(max_second + 1):
        lats = merged_buckets.get(second, [])
        errs = merged_errors.get(second, 0)
        if lats:
            import numpy as np

            arr = np.array(lats, dtype=np.int64)
            windows.append(
                TimeWindow(
                    second=second,
                    ops=len(lats),
                    errors=errs,
                    p50_ns=float(np.percentile(arr, 50)),
                    p95_ns=float(np.percentile(arr, 95)),
                    p99_ns=float(np.percentile(arr, 99)),
                )
            )
        elif errs > 0:
            windows.append(TimeWindow(second=second, ops=0, errors=errs))

    return windows


# ---------------------------------------------------------------------------
# Single-target runner (one iteration)
# ---------------------------------------------------------------------------


def run_target(
    scenario: Scenario,
    target: TargetConfig,
    rng: random.Random | None = None,
) -> TargetResult:
    """Run a single iteration for one target."""
    factory_cls = get_worker_factory(target.stack_id)
    factory = factory_cls()

    concurrency = scenario.load.concurrency
    warmup_s = scenario.load.warmup.duration
    duration_s = scenario.load.duration

    workers: list[Worker] = []
    for i in range(concurrency):
        w = factory.create(i)
        w.setup(dsn=target.dsn, worker_config=target.worker_config, scenario=scenario)
        w.open()
        workers.append(w)

    if warmup_s > 0:
        logger.info("Warming up %s for %ds...", target.stack_id, warmup_s)
        for w in workers:
            w.warmup(scenario.steps, warmup_s)

    barrier = threading.Barrier(concurrency)
    thread_results = [ThreadResult() for _ in range(concurrency)]
    threads: list[threading.Thread] = []

    # Create per-thread RNG if seed is provided
    thread_rngs: list[random.Random | None] = []
    if rng is not None:
        for i in range(concurrency):
            thread_rngs.append(random.Random(rng.randint(0, 2**63)))
    else:
        thread_rngs = [None] * concurrency

    gc.disable()
    run_start = time.perf_counter()

    for i in range(concurrency):
        t = threading.Thread(
            target=_worker_thread,
            args=(
                workers[i],
                scenario.steps,
                duration_s,
                barrier,
                thread_results[i],
                thread_rngs[i],
            ),
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    actual_duration = time.perf_counter() - run_start
    gc.enable()

    for w in workers:
        w.close()

    # Merge histograms and reservoir samples across threads
    merged_histograms: dict[str, HdrHistogram] = {}
    merged_samples: dict[str, list[int]] = {}
    merged_errors: dict[str, int] = {}
    all_error_samples: list[ErrorSample] = []

    for tr in thread_results:
        for step_name, hist in tr.step_histograms.items():
            if step_name not in merged_histograms:
                merged_histograms[step_name] = hist.copy()
            else:
                merged_histograms[step_name].merge(hist)
        for step_name, samples in tr.step_latencies.items():
            merged_samples.setdefault(step_name, []).extend(samples)
        for step_name, errs in tr.step_errors.items():
            merged_errors[step_name] = merged_errors.get(step_name, 0) + errs
        all_error_samples.extend(tr.error_samples)

    step_results: list[StepResult] = []
    merged_overall: HdrHistogram | None = None

    for step in scenario.steps:
        hist = merged_histograms.get(step.name)
        errs = merged_errors.get(step.name, 0)

        if hist and hist.total_count > 0:
            time_series = _merge_time_series(thread_results, step.name)
            # Cap reservoir sample to RESERVOIR_MAX
            samples = merged_samples.get(step.name, [])
            if len(samples) > RESERVOIR_MAX:
                samples = random.sample(samples, RESERVOIR_MAX)
            sr = build_step_result_from_histogram(
                step.name,
                hist,
                errs,
                actual_duration,
                samples_ns=samples,
                time_series=time_series,
            )
            step_results.append(sr)

            # Accumulate overall histogram
            if merged_overall is None:
                merged_overall = hist.copy()
            else:
                merged_overall.merge(hist)

    overall: LatencySummary | None = None
    if merged_overall is not None:
        from benchflow.core.metrics.aggregator import compute_latency_summary_from_histogram

        overall = compute_latency_summary_from_histogram(merged_overall)

    total_errors = sum(merged_errors.values())
    error_info = (
        ErrorInfo(
            count_total=total_errors,
            sample=all_error_samples[:MAX_ERROR_SAMPLES],
        )
        if total_errors > 0
        else None
    )

    return TargetResult(
        stack_id=target.stack_id,
        stack=StackInfo(
            language=target.language,
            driver=target.driver,
            orm=target.orm,
        ),
        config={
            "concurrency": concurrency,
            "duration_s": duration_s,
            "warmup_s": warmup_s,
        },
        status="ok" if total_errors == 0 else "failed",
        steps=step_results,
        overall=overall,
        errors=error_info,
        duration_s=round(actual_duration, 3),
    )


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def _introspect_target(target: TargetConfig) -> dict:
    """Create a temporary worker connection to introspect server metadata."""
    factory_cls = get_worker_factory(target.stack_id)
    factory = factory_cls()
    worker = factory.create(0)
    worker.setup(dsn=target.dsn, worker_config=target.worker_config, scenario=None)  # type: ignore[arg-type]
    try:
        worker.open()
        info = worker.introspect()
        worker.close()
        return info
    except Exception as exc:
        logger.debug("Introspection failed for %s: %s", target.stack_id, exc)
        try:
            worker.close()
        except Exception:
            pass
        return {}


# ---------------------------------------------------------------------------
# Full benchmark runner (multi-iteration)
# ---------------------------------------------------------------------------


def run_benchmark(
    scenario: Scenario,
    iterations_override: int | None = None,
    seed_override: int | None = None,
    capture_db_info: bool = False,
) -> RunResult:
    """Run a complete benchmark experiment.

    Args:
        scenario: The scenario to run.
        iterations_override: Override scenario.experiment.iterations from CLI.
        seed_override: Override scenario.experiment.seed from CLI.
        capture_db_info: Whether to capture DB server config via introspect().
    """
    scenario_dict = scenario.model_dump()
    signature = compute_scenario_signature(scenario_dict)

    n_iterations = iterations_override or scenario.experiment.iterations
    seed = seed_override if seed_override is not None else scenario.experiment.seed
    pause_between = scenario.experiment.pause_between

    # Detect DB kind from first target DSN
    db_kind = "unknown"
    db_server_version: str | None = None
    db_server_config: dict[str, str] = {}

    for target in scenario.targets:
        dsn = target.dsn.lower()
        if "postgres" in dsn:
            db_kind = "postgres"
        elif "mysql" in dsn:
            db_kind = "mysql"
        elif "cubrid" in dsn:
            db_kind = "cubrid"

        # Optionally introspect DB (skip for external targets — info comes from their output)
        if capture_db_info and not _is_external_target(target):
            try:
                info = _introspect_target(target)
                if "server_version" in info:
                    db_server_version = info["server_version"]
                if "server_config" in info:
                    db_server_config = info["server_config"]
            except Exception as exc:
                logger.debug("DB introspection failed: %s", exc)
        break

    # Environment detection
    env = EnvironmentInfo(
        cpu_model=EnvironmentInfo.detect_cpu_model(),
        memory_gb=EnvironmentInfo.detect_memory_gb(),
    )

    run_result = RunResult(
        schema_version=2,
        benchflow=BenchFlowInfo(git_sha=BenchFlowInfo.detect_git_sha()),
        environment=env,
        db=DatabaseInfo(
            kind=db_kind,
            server_version=db_server_version,
            server_config=db_server_config,
        ),
        scenario=ScenarioRef(
            name=scenario.name,
            signature=signature,
            parsed=scenario_dict,
        ),
        experiment_seed=seed,
        iterations_requested=n_iterations,
    )

    # Collect per-iteration results for cross-iteration aggregation
    # Key: stack_id -> list of step results per iteration
    iteration_results: list[IterationResult] = []
    per_stack_steps: dict[str, list[list[StepResult]]] = {}

    for iteration_idx in range(n_iterations):
        if n_iterations > 1:
            logger.info(
                "=== Iteration %d/%d ===",
                iteration_idx + 1,
                n_iterations,
            )

        # Compute per-iteration seed
        iter_seed: int | None = None
        iter_rng: random.Random | None = None
        if seed is not None:
            iter_seed = seed + iteration_idx
            iter_rng = random.Random(iter_seed)

        iteration_targets: list[TargetResult] = []

        for target in scenario.targets:
            if _is_external_target(target):
                # --- External (subprocess) worker path ---
                # The external process handles setup, warmup, measurement, and
                # teardown internally. We just spawn it and collect JSON results.
                logger.info("Running external target: %s", target.stack_id)
                try:
                    ext_runner = _get_external_runner()
                    target_result = ext_runner(scenario, target, seed=iter_seed)
                except Exception as exc:
                    logger.error("External worker %s failed: %s", target.stack_id, exc)
                    raise

                iteration_targets.append(target_result)

                if target.stack_id not in per_stack_steps:
                    per_stack_steps[target.stack_id] = []
                per_stack_steps[target.stack_id].append(target_result.steps)

                logger.info(
                    "External target %s completed: %d ops, status=%s",
                    target.stack_id,
                    sum(s.ops for s in target_result.steps),
                    target_result.status,
                )
            else:
                # --- In-process (Python) worker path ---
                factory_cls = get_worker_factory(target.stack_id)
                factory = factory_cls()
                setup_worker: Worker | None = None

                try:
                    # Execute setup queries if defined
                    if scenario.setup and scenario.setup.queries:
                        setup_worker = factory.create(-1)  # Special index for setup worker
                        setup_worker.setup(
                            dsn=target.dsn,
                            worker_config=target.worker_config,
                            scenario=scenario,
                        )
                        setup_worker.open()
                        _execute_setup_queries(setup_worker, scenario.setup.queries)
                        setup_worker.close()
                        setup_worker = None

                    # Run the actual benchmark iteration
                    logger.info("Running target: %s", target.stack_id)
                    target_result = run_target(scenario, target, rng=iter_rng)
                    iteration_targets.append(target_result)

                    # Track for cross-iteration aggregation
                    if target.stack_id not in per_stack_steps:
                        per_stack_steps[target.stack_id] = []
                    per_stack_steps[target.stack_id].append(target_result.steps)

                    logger.info(
                        "Target %s completed: %d ops, status=%s",
                        target.stack_id,
                        sum(s.ops for s in target_result.steps),
                        target_result.status,
                    )

                finally:
                    # Execute teardown queries if defined
                    if scenario.teardown and scenario.teardown.queries:
                        td_worker = factory.create(-1)
                        td_worker.setup(
                            dsn=target.dsn,
                            worker_config=target.worker_config,
                            scenario=scenario,
                        )
                        try:
                            td_worker.open()
                            _execute_teardown_queries(td_worker, scenario.teardown.queries)
                            td_worker.close()
                        except Exception as exc:
                            logger.warning("Teardown failed for %s: %s", target.stack_id, exc)
                            try:
                                td_worker.close()
                            except Exception:
                                pass

                    # Close setup worker if still open (error path)
                    if setup_worker is not None:
                        try:
                            setup_worker.close()
                        except Exception:
                            pass

        # Build iteration result
        iter_result = IterationResult(
            iteration=iteration_idx,
            seed=iter_seed,
            targets=iteration_targets,
            duration_s=sum(t.duration_s for t in iteration_targets),
        )
        iteration_results.append(iter_result)

        # Pause between iterations (skip after last)
        if n_iterations > 1 and iteration_idx < n_iterations - 1 and pause_between > 0:
            logger.info("Pausing %.1fs between iterations...", pause_between)
            time.sleep(pause_between)

    # Populate top-level targets with last iteration (backward compat)
    if iteration_results:
        run_result.targets = iteration_results[-1].targets

    # Store all iteration results
    if n_iterations > 1:
        run_result.iterations = iteration_results

        # Compute cross-iteration aggregates
        agg_rng = random.Random(seed) if seed is not None else None
        aggregates: list[AggregateTargetResult] = []
        for stack_id, step_lists in per_stack_steps.items():
            agg = compute_cross_iteration_aggregate(step_lists, stack_id, rng=agg_rng)
            aggregates.append(agg)
        run_result.aggregate = aggregates

    return run_result
