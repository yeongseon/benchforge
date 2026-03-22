# Scenario DSL Reference

This is the complete specification of BenchForge's scenario YAML format.
Researchers should treat this as a contract — the schema is versioned and
backward-compatible changes will be documented.

## Schema Version

Current schema version: **2** (BenchForge 0.1.x)

## Complete Schema

```yaml
# Required
name: string                    # Scenario identifier

# Optional
description: string | null      # Human-readable description

# Optional — SQL queries for database state management
setup:
  queries: list[string]         # Executed before each iteration (fail-fast)

teardown:
  queries: list[string]         # Executed after each iteration (best-effort)

# Required — at least one step
steps:
  - name: string               # Step identifier (unique within scenario)
    query: string               # SQL query with %(param)s placeholders
    params:                     # Optional parameter generators
      param_name: string        # Generator expression or literal value

# Optional — load profile (defaults shown)
load:
  concurrency: int              # Number of concurrent worker threads (default: 1, min: 1)
  duration: int                 # Measurement duration in seconds (default: 10, min: 1)
  warmup:
    duration: int               # Warmup duration in seconds (default: 5)

# Optional — multi-iteration experiment (defaults shown)
experiment:
  iterations: int               # Number of iterations (default: 1, min: 1)
  seed: int | null              # Base random seed (default: null)
  pause_between: float          # Seconds between iterations (default: 5.0, min: 0)

# Optional — target stacks to benchmark
targets:
  - name: string               # Display name (e.g., "psycopg-raw")
    stack_id: string            # Worker registry key (e.g., "python+psycopg")
    language: string            # Language identifier (default: "python")
    driver: string              # Driver name (e.g., "psycopg", "sqlalchemy")
    orm: string | null          # ORM name if applicable (default: null)
    dsn: string                 # Database connection string
    worker_config: object       # Optional driver-specific configuration (default: {})
```

---

## Field Reference

### `name` (required)

```yaml
name: basic-select
```

A string identifier for the scenario. Used in report titles, filenames, and
comparison output. Should be descriptive and kebab-case by convention.

### `description` (optional)

```yaml
description: "Basic point SELECT benchmark: psycopg vs SQLAlchemy"
```

Human-readable description. Included in the result JSON and HTML report.

### `setup` (optional)

```yaml
setup:
  queries:
    - "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, name VARCHAR(100))"
    - "INSERT INTO users (name) SELECT 'user_' || i FROM generate_series(1, 1000) AS i ON CONFLICT DO NOTHING"
```

SQL queries executed **before each iteration** using a dedicated setup worker.
Queries run sequentially. If any query fails, the run aborts immediately.

**Best practices:**
- Make queries idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`)
- Create all required tables and seed data here
- Do not depend on external database state

### `teardown` (optional)

```yaml
teardown:
  queries:
    - "TRUNCATE TABLE users"
    - "DROP TABLE IF EXISTS temp_results"
```

SQL queries executed **after each iteration**. Queries run sequentially.
Failures are **logged but do not abort** — this ensures cleanup runs even
if the benchmark fails.

### `steps` (required, min: 1)

```yaml
steps:
  - name: point-select
    query: "SELECT * FROM users WHERE id = %(id)s"
    params:
      id: "random_int(1, 1000)"

  - name: range-scan
    query: "SELECT * FROM users WHERE id BETWEEN %(low)s AND %(high)s"
    params:
      low: "random_int(1, 900)"
      high: "random_int(901, 1000)"
```

Each step defines a query to execute during the measurement phase. Steps are
executed in round-robin order by each worker thread.

#### `steps[].name` (required)

Unique identifier within the scenario. Appears in results, charts, and
comparison output.

#### `steps[].query` (required)

SQL query string. Use `%(param_name)s` syntax for parameterized queries.
BenchForge translates this to the appropriate driver syntax:
- **psycopg**: `%(param_name)s` (native)
- **SQLAlchemy**: `:param_name` (auto-translated)

#### `steps[].params` (optional)

Parameter generators, keyed by parameter name. Supported generators:

| Generator | Syntax | Description | Example |
|-----------|--------|-------------|---------|
| `random_int` | `random_int(low, high)` | Uniform random integer in [low, high] | `random_int(1, 1000)` |
| `random_choice` | `random_choice(a, b, c)` | Random selection from comma-separated values | `random_choice('read', 'write', 'update')` |
| Literal | `42` or `"hello"` | Fixed value (no generation) | `42` |

Parameters are resolved fresh on **every execution**. With a seed, parameter
generation is deterministic.

### `load` (optional)

```yaml
load:
  concurrency: 4        # Default: 1
  duration: 10           # Default: 10 (seconds)
  warmup:
    duration: 3          # Default: 5 (seconds)
```

#### `load.concurrency`

Number of concurrent worker threads. Each thread gets its own Worker instance
and database connection. Threads are synchronized at start using a barrier.

- **Minimum**: 1
- **Default**: 1

#### `load.duration`

Measurement duration in seconds. This is the time during which latencies
are recorded (after warmup completes).

- **Minimum**: 1
- **Default**: 10

#### `load.warmup.duration`

Warmup duration in seconds. During warmup, queries are executed but not
measured. This allows JIT compilation, connection pool establishment, and
database cache warming.

- **Default**: 5
- Set to 0 to skip warmup

### `experiment` (optional)

```yaml
experiment:
  iterations: 5          # Default: 1
  seed: 42               # Default: null
  pause_between: 2.0     # Default: 5.0
```

#### `experiment.iterations`

Number of times to repeat the complete workload. Each iteration includes
setup, warmup, measurement, and teardown.

- **Minimum**: 1
- **Default**: 1
- **Recommended**: 5+ for publication, 3+ for engineering evaluation

#### `experiment.seed`

Base random seed for reproducible parameter generation.

- **Default**: null (non-deterministic)
- Iteration _i_ uses seed `seed + i`
- Each thread within an iteration gets its own derived RNG

When set, the exact same sequence of parameters is generated on every run,
enabling true reproducibility.

#### `experiment.pause_between`

Seconds of idle time between iterations.

- **Minimum**: 0
- **Default**: 5.0
- **Purpose**: Allows OS buffers, database caches, and GC state to stabilize

### `targets` (optional, but required for execution)

```yaml
targets:
  - name: psycopg-raw
    stack_id: python+psycopg
    language: python
    driver: psycopg
    dsn: "postgresql://user:pass@host:port/dbname"
    worker_config: {}
```

#### `targets[].name`

Display name for the target. Used in CLI output and report tables.

#### `targets[].stack_id`

Key used to look up the worker factory in the registry. Must match a
registered worker.

**Built-in stack IDs:**
| Stack ID | Worker |
|----------|--------|
| `python+psycopg` | `PsycopgWorker` — raw psycopg3 |
| `python+sqlalchemy` | `SQLAlchemyWorker` — SQLAlchemy Core |

#### `targets[].language`

Language identifier. Default: `"python"`. Used in result metadata.

#### `targets[].driver`

Driver name. Used in result metadata.

#### `targets[].orm`

ORM name, if applicable. Default: `null`. For raw driver usage, omit this field.

#### `targets[].dsn`

Database connection string. Format depends on the driver:
- **psycopg**: `postgresql://user:pass@host:port/dbname`
- **SQLAlchemy**: `postgresql+psycopg://user:pass@host:port/dbname`

#### `targets[].worker_config`

Optional dictionary of driver-specific configuration. Passed to
`worker.setup()` and available for custom worker implementations.

---

## Validation

BenchForge validates all scenario files against Pydantic models at load time.
Invalid scenarios produce clear error messages:

```
$ bench run invalid.yaml
Error: 1 validation error for Scenario
steps
  Value error, scenario must have at least one step
```

Validation rules:
- `name` is required
- At least one step is required
- `concurrency` must be >= 1
- `duration` must be >= 1
- `iterations` must be >= 1
- `pause_between` must be >= 0

---

## Complete Example

```yaml
name: oltp-comparison
description: "OLTP workload: point queries + inserts across driver stacks"

setup:
  queries:
    - >
      CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        balance NUMERIC(12,2) DEFAULT 1000.00,
        created_at TIMESTAMP DEFAULT now()
      )
    - >
      INSERT INTO accounts (name, balance)
      SELECT 'account_' || i, 1000.00 + (random() * 9000)::numeric(12,2)
      FROM generate_series(1, 10000) AS i
      ON CONFLICT DO NOTHING

teardown:
  queries:
    - "TRUNCATE TABLE accounts"

steps:
  - name: point-select
    query: "SELECT * FROM accounts WHERE id = %(id)s"
    params:
      id: "random_int(1, 10000)"

  - name: balance-update
    query: "UPDATE accounts SET balance = balance + 1.00 WHERE id = %(id)s"
    params:
      id: "random_int(1, 10000)"

load:
  concurrency: 8
  duration: 30
  warmup:
    duration: 5

experiment:
  iterations: 5
  seed: 42
  pause_between: 3.0

targets:
  - name: psycopg-raw
    stack_id: python+psycopg
    language: python
    driver: psycopg
    dsn: "postgresql://postgres:postgres@localhost:5432/benchflow"

  - name: sqlalchemy-core
    stack_id: python+sqlalchemy
    language: python
    driver: sqlalchemy
    dsn: "postgresql+psycopg://postgres:postgres@localhost:5432/benchflow"
```
