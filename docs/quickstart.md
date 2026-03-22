# Quick Start Guide

This guide walks you through installing BenchForge, running your first benchmark,
and generating a publication-quality report.

## Prerequisites

- **Python 3.10+**
- **PostgreSQL** (or any supported database) — Docker recommended
- **pip** or **pipx**

## 1. Install BenchForge

```bash
# From PyPI (once published)
pip install benchforge

# From source (development)
git clone https://github.com/yeongseon/benchforge.git
cd benchflow
pip install -e ".[dev]"
```

## 2. Start a Database

BenchForge ships a `docker-compose.yml` for PostgreSQL 16:

```bash
docker compose up -d
```

This starts PostgreSQL on port **5433** (mapped to container port 5432) with:
- User: `postgres`
- Password: `postgres`
- Database: `benchflow`

## 3. Write a Scenario

Create a file `my_scenario.yaml`:

```yaml
name: my-first-benchmark
description: "Compare psycopg vs SQLAlchemy on point SELECTs"

setup:
  queries:
    - >
      CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100),
        email VARCHAR(200)
      )
    - >
      INSERT INTO users (name, email)
      SELECT 'user_' || i, 'user_' || i || '@example.com'
      FROM generate_series(1, 1000) AS i
      ON CONFLICT DO NOTHING

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
  iterations: 3
  seed: 42
  pause_between: 2.0

targets:
  - name: psycopg-raw
    stack_id: python+psycopg
    driver: psycopg
    dsn: "postgresql://postgres:postgres@localhost:5433/benchflow"

  - name: sqlalchemy-core
    stack_id: python+sqlalchemy
    driver: sqlalchemy
    dsn: "postgresql+psycopg://postgres:postgres@localhost:5433/benchflow"
```

See [Scenario Reference](scenario-reference.md) for full DSL documentation.

## 4. Run the Benchmark

```bash
bench run my_scenario.yaml -v
```

Options:
- `-v` / `--verbose` — Show progress logs
- `-n 5` / `--iterations 5` — Override iteration count
- `--seed 123` — Override random seed
- `-o results.json` — Specify output path
- `--capture-db-info` — Record PostgreSQL server configuration

Output is saved as JSON in `reports/<run_id>.json` by default.

## 5. Generate a Report

```bash
bench report reports/<run_id>.json
```

This produces a self-contained HTML file with:
- Summary table with latency percentiles (p50, p95, p99, p99.9)
- Latency bar chart with 95% CI error bars (multi-iteration)
- Throughput bar chart
- ECDF (cumulative distribution) plot
- Time-series: throughput and p95 latency over time
- Environment metadata and database configuration

## 6. Compare Two Runs

```bash
bench compare reports/run_a.json reports/run_b.json
```

Outputs a comparison table showing latency and throughput ratios between
baseline and contender, with a verdict (faster / slower / same).

## See Also

- [Core Concepts](concepts.md)
- [Scenario DSL Reference](scenario-reference.md)

## What's Next?

- [Concepts](concepts.md) — Core abstractions (scenarios, workers, iterations)
- [Scenario Reference](scenario-reference.md) — Full DSL specification
- [Methodology](methodology.md) — Statistical methods (HDR histogram, bootstrap CI)
- [Reproducibility](reproducibility.md) — Checklist for publishing benchmark results
- [Architecture](architecture.md) — System design and extension points
