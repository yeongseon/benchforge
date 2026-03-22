# BenchFlow

[![CI](https://github.com/yeongseon/benchflow/actions/workflows/ci.yml/badge.svg)](https://github.com/yeongseon/benchflow/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/yeongseon/benchflow/graph/badge.svg)](https://codecov.io/gh/yeongseon/benchflow)
[![Release](https://github.com/yeongseon/benchflow/actions/workflows/publish-pypi.yml/badge.svg)](https://github.com/yeongseon/benchflow/actions/workflows/publish-pypi.yml)
[![Security Scans](https://github.com/yeongseon/benchflow/actions/workflows/security.yml/badge.svg)](https://github.com/yeongseon/benchflow/actions/workflows/security.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/benchflow.svg)](https://pypi.org/project/benchflow/)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://yeongseon.github.io/benchflow/)

Research-grade, scenario-based database benchmark platform for DB researchers and engineers.

Compare different DB access stacks — driver, ORM, language — under identical workloads with statistical rigor suitable for academic publication (VLDB, SIGMOD, OSDI) and professional engineering evaluation.

## Why BenchFlow?

Most database benchmark scripts are one-off, ad-hoc, and produce results that cannot be reproduced or trusted. BenchFlow addresses this by providing:

- **Statistical rigor** — Multi-iteration experiments with bootstrap confidence intervals, not single-run "eyeball" comparisons
- **Reproducibility** — Seed control, full environment capture, setup/teardown isolation, and versioned result schemas
- **Publication quality** — Reports designed for academic papers: ECDF plots, CI error bars, booktabs tables, colorblind-safe palette
- **Apples-to-apples comparison** — Run the exact same workload across different drivers, ORMs, or languages with `bench compare`

BenchFlow is **not** a distributed load generator, a database provisioning tool, or a replacement for TPC benchmarks. It is a focused tool for comparing database access stacks under controlled conditions.

## Key Features

- **Multi-iteration experiments** with seed control for reproducibility
- **HDR histogram** (in-house, zero-dep) for O(1) latency recording with configurable precision
- **Cross-iteration statistics**: mean, stdev, CV, 95% CI (bootstrap)
- **Time-series collection** in 1-second windows: throughput, errors, latency quantiles
- **Publication-quality HTML reports**: paper theme (Crimson Pro + Source Sans 3, booktabs tables), ECDF plots, CI error bars, time-series charts, Okabe-Ito colorblind-safe palette
- **Environment capture**: CPU, memory, OS, Python version, DB server config
- **Setup/teardown** queries per iteration for run isolation
- **Warmup phase** excluded from measurement

## Installation

### From PyPI (recommended)

```bash
pip install benchflow
```

### From source (development)

```bash
git clone https://github.com/yeongseon/benchflow.git
cd benchflow
pip install -e ".[dev]"
```

### With pipx (isolated install)

```bash
pipx install benchflow
```

### Dependencies

BenchFlow requires Python 3.10+ and includes the following dependencies:

| Package | Purpose |
|---------|---------|
| `psycopg[binary]` | PostgreSQL driver (psycopg3) |
| `sqlalchemy` | SQLAlchemy Core/ORM driver |
| `pydantic` | Scenario schema validation |
| `pyyaml` | YAML scenario loading |
| `typer` + `rich` | CLI interface |
| `jinja2` + `plotly` | HTML report generation |
| `numpy` | Bootstrap CI computation |

## Quick Start

```bash
# 1. Start PostgreSQL
docker compose up -d

# 2. Install BenchFlow
pip install -e ".[dev]"

# 3. Run a benchmark (5 iterations, seed=42)
bench run scenarios/basic.yaml -v

# 4. Override iterations/seed from CLI
bench run scenarios/basic.yaml -n 10 --seed 123

# 5. Compare two runs
bench compare reports/run1.json reports/run2.json

# 6. Generate HTML report
bench report reports/run1.json
```

For a detailed walkthrough, see [docs/quickstart.md](docs/quickstart.md).

## Example Scenarios

BenchFlow ships with ready-to-use example scenarios in [`examples/`](examples/):

| Scenario | File | Description |
|----------|------|-------------|
| OLTP Point Lookups | [`oltp_point_lookups.yaml`](examples/oltp_point_lookups.yaml) | Single-row SELECT by PK — measures point-query latency and driver overhead |
| Analytical Aggregation | [`analytical_aggregation.yaml`](examples/analytical_aggregation.yaml) | GROUP BY over 500K rows — full-table scans, aggregation, OLAP-style queries |
| Connection Pool Stress | [`connection_pool_stress.yaml`](examples/connection_pool_stress.yaml) | 32-worker concurrency stress — connection overhead and latency degradation |
| Mixed Read/Write | [`mixed_read_write.yaml`](examples/mixed_read_write.yaml) | Banking-style OLTP — interleaved SELECTs, UPDATEs, and INSERTs |
| Index vs Seq Scan | [`index_scan_vs_seq_scan.yaml`](examples/index_scan_vs_seq_scan.yaml) | Selectivity impact on query planner — index scan vs sequential scan paths |

Run any example:

```bash
bench run examples/oltp_point_lookups.yaml -v
bench run examples/mixed_read_write.yaml -n 3 --seed 7
```

## Scenario Format

```yaml
name: basic-select
description: "Basic point SELECT benchmark: psycopg vs SQLAlchemy"

setup:
  queries:
    - "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, name VARCHAR(100))"
    - "INSERT INTO users (name) SELECT 'user_' || i FROM generate_series(1, 1000) AS i ON CONFLICT DO NOTHING"

teardown:
  queries:
    - "TRUNCATE TABLE users"

steps:
  - name: point-select
    query: "SELECT * FROM users WHERE id = %(id)s"
    params:
      id: "random_int(1, 1000)"

load:
  concurrency: 4
  duration: 10
  warmup:
    duration: 3

experiment:
  iterations: 5
  seed: 42
  pause_between: 2.0

targets:
  - name: psycopg-raw
    stack_id: python+psycopg
    driver: psycopg
    dsn: "postgresql://postgres:postgres@localhost:5432/benchflow"
  - name: sqlalchemy-core
    stack_id: python+sqlalchemy
    driver: sqlalchemy
    dsn: "postgresql+psycopg://postgres:postgres@localhost:5432/benchflow"
```

For the complete DSL specification, see [docs/scenario-reference.md](docs/scenario-reference.md).

## Architecture

```
Controller (Python Core)
  +-- Scenario Engine       YAML DSL -> Pydantic models + ExperimentConfig
  +-- Threaded Runner       barrier-sync, perf_counter_ns, GC control, multi-iteration
  +-- HDR Histogram         O(1) record, log-bucket, mergeable across threads
  +-- Metrics Aggregator    histogram percentiles, bootstrap CI, cross-iteration stats
  +-- Report Generator      publication-quality HTML (paper + dark themes)

Workers (per-thread lifecycle)
  +-- PsycopgWorker         raw psycopg3, one connection per thread
  +-- SQLAlchemyWorker      SQLAlchemy Core, shared engine, param translation
```

For a detailed architecture walkthrough, see [docs/architecture.md](docs/architecture.md).

## Project Structure

```
benchflow/
  benchflow/
    core/
      runner/runner.py          # Multi-iteration threaded benchmark execution
      scenario/schema.py        # Pydantic scenario models + ExperimentConfig
      scenario/loader.py        # YAML loading
      metrics/aggregator.py     # Latency stats, bootstrap CI, cross-iteration aggregation
      metrics/histogram.py      # HDR-style log-bucket histogram
      report/html.py            # Publication-quality HTML report generator
      result.py                 # Versioned result JSON schema (v2)
    cli/main.py                 # Typer CLI (run/compare/report)
    workers/
      protocol.py               # Worker ABC + registry
      python/
        psycopg_worker.py
        sqlalchemy_worker.py
  scenarios/basic.yaml
  examples/                     # Ready-to-use benchmark scenarios
  docs/                         # Comprehensive documentation
  tests/
```

## CLI Reference

```
bench run <scenario.yaml> [OPTIONS]
  -o, --output          Output JSON path
  -n, --iterations      Override iteration count
  --seed                Override random seed
  --capture-db-info     Capture DB server config via introspect()
  -v, --verbose         Enable verbose logging

bench compare <baseline.json> <contender.json> [OPTIONS]
  -o, --output          Output comparison JSON

bench report <result.json> [OPTIONS]
  -o, --output          Output HTML path
```

> **CLI Stability Note**: The `bench run`, `bench compare`, and `bench report` commands are considered stable as of v0.1.0. Subcommand names and core flags (`-o`, `-n`, `--seed`, `-v`) will follow semantic versioning — breaking changes only in major versions.

## Documentation

| Document | Description |
|----------|-------------|
| [Quick Start](docs/quickstart.md) | Install, run, report, compare — step by step |
| [Concepts](docs/concepts.md) | Scenarios, steps, targets, workers, iterations, result schema |
| [Methodology](docs/methodology.md) | Clock sources, HDR histograms, bootstrap CI, time-series |
| [Reproducibility](docs/reproducibility.md) | Pre/during/post benchmark checklists, pitfalls |
| [Scenario Reference](docs/scenario-reference.md) | Complete DSL specification with every field documented |
| [Architecture](docs/architecture.md) | System overview, components, execution flow, extension points |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, code style, and guidelines for adding scenarios and workers.

## Citing BenchFlow

If you use BenchFlow in your research, please cite it:

```bibtex
@software{choe2026benchflow,
  title  = {BenchFlow: Research-Grade Database Benchmark Platform},
  author = {Choe, Yeongseon},
  year   = {2026},
  url    = {https://github.com/yeongseon/benchflow},
}
```

See [`CITATION.cff`](CITATION.cff) for machine-readable citation metadata.

## License

MIT
