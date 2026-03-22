# Architecture

This document describes BenchForge's internal architecture, component design,
and extension points.

## System Overview

```
┌──────────────────────────────────────────────────────────┐
│                       CLI Layer                          │
│                  (Typer + Rich console)                   │
│              bench run / compare / report                 │
└──────────────┬──────────────┬──────────────┬─────────────┘
               │              │              │
    ┌──────────▼──────┐  ┌────▼────┐  ┌──────▼──────┐
    │  Scenario Engine │  │ Compare │  │   Report    │
    │  (YAML → Model)  │  │  Logic  │  │ Generator   │
    └──────────┬──────┘  └─────────┘  └─────────────┘
               │
    ┌──────────▼──────────────────────────────────────┐
    │              Benchmark Runner                    │
    │  Multi-iteration orchestration + thread barrier  │
    │  Setup/teardown per iteration                    │
    └──────────┬──────────────────────────────────────┘
               │
    ┌──────────▼──────────────────────────────────────┐
    │            Worker Threads (N concurrent)         │
    │   Each thread: Worker.execute() in tight loop    │
    │   HDR Histogram + reservoir sample + time-series │
    └──────────┬──────────────────────────────────────┘
               │
    ┌──────────▼──────────────────────────────────────┐
    │              Metrics Pipeline                    │
    │   Merge histograms → percentiles → aggregate    │
    │   Bootstrap CI → AggregateResult                 │
    └─────────────────────────────────────────────────┘
```

## Component Details

### Scenario Engine

**Files:** `benchflow/core/scenario/schema.py`, `benchflow/core/scenario/loader.py`

Responsibilities:
- Parse YAML scenario files into Pydantic models
- Validate all fields (types, ranges, required fields)
- Resolve parameter generators (`random_int`, `random_choice`)

Key models:
- `Scenario` — top-level container
- `Step` — individual query + params
- `LoadConfig` — concurrency, duration, warmup
- `ExperimentConfig` — iterations, seed, pause
- `TargetConfig` — stack definition + DSN
- `SetupTeardown` — SQL query lists

### Benchmark Runner

**File:** `benchflow/core/runner/runner.py` (582 lines)

This is the core execution engine. It orchestrates:

1. **Multi-iteration loop** — repeats the full workload N times
2. **Setup/teardown** — per-iteration database state management
3. **Worker lifecycle** — create → setup → open → warmup → measure → close
4. **Thread management** — barrier-synchronized concurrent execution
5. **Data collection** — HDR histogram, reservoir sample, time-series buckets

#### Execution Flow

```
run_benchmark(scenario)
  ├── Detect DB kind from DSN
  ├── Optionally introspect target (server version, config)
  ├── Capture environment (CPU, memory, OS)
  │
  ├── For each iteration:
  │   ├── For each target:
  │   │   ├── Execute setup queries (fail-fast)
  │   │   ├── run_target(scenario, target, rng)
  │   │   │   ├── Create N workers (one per thread)
  │   │   │   ├── worker.setup() → worker.open()
  │   │   │   ├── worker.warmup() (excluded from measurement)
  │   │   │   ├── gc.disable()
  │   │   │   ├── Barrier.wait() — synchronize all threads
  │   │   │   ├── _worker_thread() — tight loop for duration_s
  │   │   │   │   ├── worker.execute(step)
  │   │   │   │   ├── Record latency in HDR histogram
  │   │   │   │   ├── Reservoir sample for ECDF
  │   │   │   │   └── Time-series bucketing
  │   │   │   ├── gc.enable()
  │   │   │   ├── Merge per-thread histograms and samples
  │   │   │   └── Build StepResult + TargetResult
  │   │   └── Execute teardown queries (best-effort)
  │   └── Build IterationResult
  │
  ├── Compute cross-iteration aggregates (bootstrap CI)
  └── Return RunResult
```

#### Thread Synchronization

```python
barrier = threading.Barrier(concurrency)
# In each thread:
barrier.wait()  # All threads start measuring simultaneously
```

#### Per-Thread Data Structures

Each thread maintains its own:
- `HdrHistogram` per step (no locking needed)
- Reservoir sample list per step
- Time-series buckets (second → latency list)
- Error samples (capped at 50)

After all threads complete, data is merged:
- Histograms: `hist_a.merge(hist_b)` — O(buckets)
- Reservoir samples: concatenated, then re-sampled to 10,000
- Time-series: per-second latencies merged across threads

### HDR Histogram

**File:** `benchflow/core/metrics/histogram.py` (377 lines)

In-house implementation of a log-linear histogram. Key design properties:

| Property | Value |
|----------|-------|
| Record complexity | O(1) |
| Merge complexity | O(buckets) |
| Percentile complexity | O(buckets) |
| Default precision | 3 significant digits (~0.1% relative error) |
| Default range | 1 ns to 3,600,000,000,000 ns (1 hour) |
| Memory | ~8 KB per histogram |
| Dependencies | None (pure Python + math) |

The histogram is the primary data structure for latency recording. It replaces
naive list-based approaches that consume O(n) memory and require O(n log n)
sorting for percentile computation.

### Metrics Aggregator

**File:** `benchflow/core/metrics/aggregator.py` (236 lines)

Provides:
- `compute_latency_summary_from_histogram()` — extract percentiles from HDR histogram
- `reservoir_sample()` — bounded random sampling
- `bootstrap_ci()` — bootstrap confidence intervals (10,000 resamples)
- `compute_aggregate_metric()` — mean, stdev, CV, CI
- `compute_cross_iteration_aggregate()` — per-step aggregation across iterations

### Result Schema

**File:** `benchflow/core/result.py` (348 lines)

Pydantic models for the versioned JSON result format:

```
RunResult (v2)
├── BenchForgeInfo (version, git_sha)
├── EnvironmentInfo (hostname, OS, CPU, memory, Python)
├── DatabaseInfo (kind, server_version, server_config)
├── ScenarioRef (name, signature, parsed YAML)
├── targets: [TargetResult]          # Last iteration (backward compat)
│   ├── StackInfo (language, driver, orm)
│   ├── steps: [StepResult]
│   │   ├── LatencySummary (min, max, mean, stdev, p50-p9999)
│   │   ├── samples_ns: [int]       # Reservoir sample (max 10,000)
│   │   └── time_series: [TimeWindow]
│   └── errors: ErrorInfo
├── iterations: [IterationResult]    # All iterations
└── aggregate: [AggregateTargetResult]  # Cross-iteration stats
    └── steps: [AggregateStepResult]
        ├── ops: AggregateMetric (mean, stdev, CV, CI)
        ├── throughput_ops_s: AggregateMetric
        ├── p50_ns: AggregateMetric
        ├── p95_ns: AggregateMetric
        ├── p99_ns: AggregateMetric
        └── p999_ns: AggregateMetric
```

### Report Generator

**File:** `benchflow/core/report/html.py` (710 lines)

Generates a self-contained HTML report using Jinja2 templates. Features:

- **Paper theme** (default): white background, Crimson Pro headings, Source Sans 3 body,
  booktabs-style tables
- **Dark theme**: toggleable, GitHub-dark inspired
- **Charts** via Plotly.js:
  - Latency bar chart (p50/p95/p99) with optional CI error bars
  - Throughput bar chart with optional CI error bars
  - ECDF (empirical CDF) from reservoir samples
  - Time-series: throughput + p95 latency over time (dual y-axis)
- **Okabe-Ito** colorblind-safe palette
- Print-optimized CSS
- Zero external dependencies at render time (fonts loaded from Google Fonts)

### Worker Protocol

**File:** `benchflow/workers/protocol.py` (91 lines)

Abstract base class + factory pattern + global registry:

```python
class Worker(ABC):
    def setup(*, dsn, worker_config, scenario) -> None
    def open() -> None
    def warmup(steps, duration_s) -> None
    def execute(step) -> None
    def execute_raw(query) -> None
    def introspect() -> dict
    def close() -> None

class WorkerFactory(ABC):
    def create(thread_index) -> Worker

WORKER_REGISTRY: dict[str, type[WorkerFactory]] = {}
register_worker(stack_id, factory_cls) -> None
get_worker_factory(stack_id) -> type[WorkerFactory]
```

### CLI

**File:** `benchflow/cli/main.py` (249 lines)

Typer-based CLI with Rich console output:

| Command | Description |
|---------|-------------|
| `bench run <scenario.yaml>` | Run benchmark, save JSON result |
| `bench compare <a.json> <b.json>` | Compare two runs (ratios + verdict) |
| `bench report <result.json>` | Generate HTML report |

---

## Extension Points

### Adding a New Worker

1. Create a new file in `benchflow/workers/` (e.g., `benchflow/workers/python/asyncpg_worker.py`)
2. Implement `Worker` and `WorkerFactory`:

```python
from benchflow.workers.protocol import Worker, WorkerFactory, register_worker

class AsyncpgWorker(Worker):
    def setup(self, *, dsn, worker_config, scenario):
        self._dsn = dsn

    def open(self):
        # Establish connection
        ...

    def execute(self, step):
        # Execute query
        ...

    def close(self):
        # Release connection
        ...

class AsyncpgWorkerFactory(WorkerFactory):
    def create(self, thread_index):
        return AsyncpgWorker()

register_worker("python+asyncpg", AsyncpgWorkerFactory)
```

3. Import the module in `benchflow/cli/main.py`:
```python
import benchflow.workers.python.asyncpg_worker  # noqa: F401
```

4. Use in scenarios:
```yaml
targets:
  - name: asyncpg-raw
    stack_id: python+asyncpg
    driver: asyncpg
    dsn: "postgresql://..."
```

### Adding New Metrics

The metrics pipeline is modular. To add new per-step metrics:

1. Add fields to `StepResult` in `benchflow/core/result.py`
2. Populate them in `build_step_result_from_histogram()` in `aggregator.py`
3. Add cross-iteration aggregation in `compute_cross_iteration_aggregate()`
4. Update the HTML template in `html.py` to display them

---

## Design Principles

1. **Zero runtime dependencies for core** — HDR histogram is pure Python
2. **Thread-local everything** — no shared mutable state during measurement
3. **Fail-fast setup, best-effort teardown** — protect data integrity
4. **Versioned schemas** — result JSON includes `schema_version` for forward compatibility
5. **Publication-first reporting** — reports are designed for papers, not dashboards
6. **Reproducibility by default** — seed control, environment capture, versioned results

## See Also

- [Scenario DSL Reference](scenario-reference.md)
