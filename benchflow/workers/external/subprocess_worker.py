"""Subprocess-based external worker — spawns a benchmark binary and collects JSON results.

Usage in scenario YAML:

    targets:
      - name: go-cubrid
        stack_id: external
        language: go
        driver: cubrid-go
        dsn: "cubrid://dba:@localhost:33000/benchdb"
        worker_config:
          command: ["go", "run", "./cmd/benchflow_worker"]
          timeout: 300  # seconds, optional (default 600)
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from benchflow.core.result import (
    ErrorInfo,
    LatencySummary,
    StackInfo,
    StepResult,
    TargetResult,
    TimeWindow,
)
from benchflow.core.scenario.schema import Scenario, TargetConfig
from benchflow.workers.external.protocol import (
    WorkerInput,
    WorkerInputStep,
    WorkerOutput,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600  # 10 minutes


def run_external_target(
    scenario: Scenario,
    target: TargetConfig,
    seed: int | None = None,
) -> TargetResult:
    """Spawn an external worker process and return its results as a TargetResult.

    The external process receives a JSON config file path as its first argument
    and must write a ``WorkerOutput``-compatible JSON to stdout.
    """
    command = target.worker_config.get("command")
    if not command:
        raise ValueError(
            f"External worker target {target.name!r} missing 'command' in worker_config. "
            "Example: worker_config: {command: ['go', 'run', './cmd/benchflow_worker']}"
        )
    if isinstance(command, str):
        command = [command]

    timeout = target.worker_config.get("timeout", DEFAULT_TIMEOUT)

    # Build input config
    worker_input = WorkerInput(
        dsn=target.dsn,
        steps=[
            WorkerInputStep(name=s.name, query=s.query, params=s.params)
            for s in scenario.steps
        ],
        concurrency=scenario.load.concurrency,
        duration_s=scenario.load.duration,
        warmup_s=scenario.load.warmup.duration,
        seed=seed,
        setup_queries=scenario.setup.queries if scenario.setup else [],
        teardown_queries=scenario.teardown.queries if scenario.teardown else [],
        worker_config={
            k: v for k, v in target.worker_config.items() if k not in ("command", "timeout")
        },
    )

    # Write config to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="benchflow_", delete=False
    ) as f:
        f.write(worker_input.model_dump_json(indent=2))
        config_path = f.name

    try:
        full_command = list(command) + [config_path]
        logger.info("Spawning external worker: %s", " ".join(full_command))

        proc = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if proc.returncode != 0:
            stderr_preview = (proc.stderr or "")[:500]
            raise RuntimeError(
                f"External worker {target.name!r} exited with code {proc.returncode}.\n"
                f"stderr: {stderr_preview}"
            )

        # Parse stdout JSON
        stdout = proc.stdout.strip()
        if not stdout:
            raise RuntimeError(
                f"External worker {target.name!r} produced no stdout output.\n"
                f"stderr: {(proc.stderr or '')[:500]}"
            )

        output = WorkerOutput.model_validate(json.loads(stdout))

        if output.status != "ok":
            raise RuntimeError(
                f"External worker {target.name!r} reported error: {output.error_message}"
            )

        return _map_to_target_result(target, output)

    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"External worker {target.name!r} timed out after {timeout}s."
        )
    finally:
        Path(config_path).unlink(missing_ok=True)


def _map_to_target_result(target: TargetConfig, output: WorkerOutput) -> TargetResult:
    """Convert WorkerOutput to benchflow's internal TargetResult."""
    steps: list[StepResult] = []
    overall_ops = 0
    overall_errors = 0

    for step_out in output.steps:
        ls = step_out.latency_summary
        step_result = StepResult(
            name=step_out.name,
            ops=step_out.ops,
            errors=step_out.errors,
            latency_summary=LatencySummary(
                min_ns=ls.min_ns,
                max_ns=ls.max_ns,
                mean_ns=ls.mean_ns,
                stdev_ns=ls.stdev_ns,
                p50_ns=ls.p50_ns,
                p95_ns=ls.p95_ns,
                p99_ns=ls.p99_ns,
                p999_ns=ls.p999_ns,
                p9999_ns=ls.p9999_ns,
            ),
            throughput_ops_s=step_out.throughput_ops_s,
            samples_ns=step_out.samples_ns,
            time_series=[
                TimeWindow(
                    second=tw.second,
                    ops=tw.ops,
                    errors=tw.errors,
                    p50_ns=tw.p50_ns,
                    p95_ns=tw.p95_ns,
                    p99_ns=tw.p99_ns,
                )
                for tw in step_out.time_series
            ],
        )
        steps.append(step_result)
        overall_ops += step_out.ops
        overall_errors += step_out.errors

    # Build overall latency summary (use first step as representative, or None)
    overall: LatencySummary | None = steps[0].latency_summary if steps else None

    error_info: ErrorInfo | None = None
    if overall_errors > 0:
        error_info = ErrorInfo(
            count_total=overall_errors,
            sample=[],
        )

    return TargetResult(
        stack_id=target.stack_id,
        stack=StackInfo(
            language=target.language,
            driver=target.driver,
            orm=target.orm,
        ),
        config=target.worker_config,
        status="ok",
        steps=steps,
        overall=overall,
        errors=error_info,
        duration_s=output.duration_s,
    )
