# Core Concepts

This document explains the fundamental abstractions in BenchForge. Understanding
these concepts is essential for writing effective scenarios and interpreting results.

## Scenario

A **scenario** is a YAML file that fully describes a benchmark experiment. It contains:

| Section | Purpose |
|---------|---------|
| `name` | Human-readable identifier |
| `description` | Optional description of what is being measured |
| `setup` | SQL queries executed before each iteration |
| `teardown` | SQL queries executed after each iteration |
| `steps` | The workload — queries to execute during measurement |
| `load` | Concurrency, duration, and warmup configuration |
| `experiment` | Multi-iteration settings (iterations, seed, pause) |
| `targets` | Database access stacks to benchmark |

A scenario is the **unit of reproducibility**. Given the same scenario file and
database state, BenchForge produces comparable results across runs.

## Step

A **step** is a single query within a scenario. Each step has:

- `name` — Identifier for the step (appears in results and charts)
- `query` — SQL query string using `%(param)s` placeholder syntax
- `params` — Optional parameter generators (e.g., `random_int(1, 1000)`)

During execution, all steps are run in round-robin order by each worker thread.
Latency is measured per-step, not per-query-type.

### Parameter Generators

BenchForge supports inline parameter generation in the scenario DSL:

| Generator | Example | Description |
|-----------|---------|-------------|
| `random_int(low, high)` | `random_int(1, 1000)` | Uniform random integer in [low, high] |
| `random_choice(a, b, c)` | `random_choice('read', 'write')` | Random selection from list |

Parameters are resolved fresh on each execution. When a seed is provided,
parameter generation is deterministic and reproducible.

## Target

A **target** defines a specific database access stack to benchmark:

```yaml
targets:
  - name: psycopg-raw           # Display name
    stack_id: python+psycopg     # Registry key for worker lookup
    language: python             # Language identifier
    driver: psycopg              # Driver name
    dsn: "postgresql://..."      # Connection string
    worker_config: {}            # Optional driver-specific config
```

Multiple targets in a single scenario are benchmarked under identical conditions
(same workload, same setup/teardown, same load profile), enabling fair comparison.

## Worker

A **worker** is the execution engine for a target. Workers implement a strict
lifecycle protocol:

```
setup() → open() → [warmup() →] execute()* → close()
```

| Method | Purpose |
|--------|---------|
| `setup()` | Store configuration (DSN, worker config). No connections yet. |
| `open()` | Establish database connection. Thread-local — never shared. |
| `warmup()` | Run queries without measurement to warm JIT, caches, etc. |
| `execute()` | Execute a single step. Runner measures latency externally. |
| `execute_raw()` | Execute raw SQL for setup/teardown (no parameter binding). |
| `introspect()` | Return server metadata (version, config) for reproducibility. |
| `close()` | Release connection and resources. |

Each concurrent thread gets its own Worker instance. Connection sharing across
threads is forbidden.

### Built-in Workers

| Stack ID | Worker | Description |
|----------|--------|-------------|
| `python+psycopg` | `PsycopgWorker` | Raw psycopg3, one connection per thread, autocommit |
| `python+sqlalchemy` | `SQLAlchemyWorker` | SQLAlchemy Core with shared engine, `text()` queries |

## Iteration

An **iteration** is a single complete execution of all steps against all targets.
Multi-iteration experiments run the full workload multiple times to measure
statistical variance.

Each iteration:
1. Executes setup queries (if defined)
2. Runs the warmup phase (excluded from measurement)
3. Measures the workload for the configured duration
4. Executes teardown queries (if defined)

Between iterations, BenchForge pauses for `pause_between` seconds (default 5.0)
to allow OS and database caches to stabilize.

## Experiment

An **experiment** is the complete multi-iteration run:

```yaml
experiment:
  iterations: 5          # Number of complete runs
  seed: 42               # Base seed for reproducibility
  pause_between: 2.0     # Seconds between iterations
```

- **iterations**: How many times to repeat the full workload. More iterations
  produce tighter confidence intervals.
- **seed**: Base seed for deterministic parameter generation. Iteration _i_ uses
  seed `seed + i`, and each thread gets its own derived RNG.
- **pause_between**: Quiet time between iterations to reduce carry-over effects.

## Result Schema

BenchForge uses a versioned JSON result schema (currently v2). Key models:

| Model | Description |
|-------|-------------|
| `RunResult` | Top-level — contains everything from a single benchmark session |
| `IterationResult` | Results for one iteration (targets, duration, seed) |
| `TargetResult` | Results for one target in one iteration (steps, overall latency, errors) |
| `StepResult` | Per-step metrics (ops, throughput, latency summary, time-series, ECDF samples) |
| `AggregateTargetResult` | Cross-iteration statistics (mean, stdev, CV, bootstrap CI) |
| `CompareResult` | Comparison between two runs (latency/throughput ratios) |

Results are saved as JSON and can be loaded for reporting, comparison, or
further analysis with external tools.

## Load Profile

The **load profile** controls how BenchForge drives the workload:

```yaml
load:
  concurrency: 4      # Number of concurrent worker threads
  duration: 10         # Measurement duration in seconds
  warmup:
    duration: 3        # Warmup duration in seconds (excluded from measurement)
```

BenchForge uses a **closed-loop** model: each thread executes queries back-to-back
as fast as possible (no artificial think time). This measures maximum throughput
under the given concurrency level.

Threads are synchronized at start using a `threading.Barrier` — all threads
begin measurement at the same instant.

## Setup and Teardown

**Setup** queries run before each iteration to prepare the database state.
**Teardown** queries run after each iteration to clean up.

```yaml
setup:
  queries:
    - "CREATE TABLE IF NOT EXISTS users (...)"
    - "INSERT INTO users (...) SELECT ..."

teardown:
  queries:
    - "TRUNCATE TABLE users"
```

This per-iteration isolation ensures each iteration starts from an identical
database state, which is critical for reproducible results.

Setup failures are fail-fast (abort the run). Teardown failures are logged
but do not abort.

## See Also

- [Statistical Methodology](methodology.md)
- [Architecture](architecture.md)
