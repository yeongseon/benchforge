# Changelog

All notable changes to BenchForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-03-19

### Added

- **Core engine**: Multi-iteration threaded benchmark runner with barrier synchronization
- **Scenario DSL**: YAML-based scenario definition with Pydantic validation
  - Steps with parameterized queries (`random_int`, `random_choice`)
  - Load profile: concurrency, duration, warmup
  - Experiment config: iterations, seed, pause between iterations
  - Setup/teardown queries for run isolation
  - Multi-target support for side-by-side comparison
- **HDR histogram**: In-house log-bucket histogram for O(1) latency recording with configurable precision
- **Metrics aggregation**: Bootstrap confidence intervals, cross-iteration statistics (mean, stdev, CV, 95% CI)
- **Time-series collection**: 1-second window throughput, errors, and latency quantiles
- **Workers**:
  - `PsycopgWorker` - raw psycopg3, one connection per thread
  - `SQLAlchemyWorker` - SQLAlchemy Core, shared engine, automatic parameter translation
- **CLI** (`bench`):
  - `bench run` - execute scenarios with optional iteration/seed overrides
  - `bench compare` - statistical comparison of two benchmark runs
  - `bench report` - generate publication-quality HTML reports
- **HTML reports**: Paper and dark themes, ECDF plots, CI error bars, time-series charts, Okabe-Ito colorblind-safe palette
- **Environment capture**: CPU, memory, OS, Python version, DB server configuration
- **Result schema v2**: Versioned JSON output with iteration-level and aggregate results
- **CI/CD**: GitHub Actions with lint, test matrix (3.10/3.12/3.13), build, integration (PostgreSQL 16), and type checking
- **OSS hygiene**: MIT license, CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates, pre-commit config
- **Documentation**: Quick start, concepts, methodology, reproducibility guide, scenario reference, architecture overview
- **Example scenarios**: OLTP point lookups, analytical aggregation, connection pool stress, mixed read/write, index vs sequential scan

[Unreleased]: https://github.com/yeongseon/benchforge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yeongseon/benchforge/releases/tag/v0.1.0
