# BenchForge

Research-grade, scenario-based database benchmark platform for DB researchers and engineers.

Compare different DB access stacks - driver, ORM, language - under identical workloads with statistical rigor suitable for academic publication (VLDB, SIGMOD, OSDI) and professional engineering evaluation.

[:material-rocket-launch: Get started in minutes](quickstart.md){ .md-button .md-button--primary }
[:material-github: View on GitHub](https://github.com/yeongseon/benchforge){ .md-button }

## Feature Highlights

<div class="grid cards" markdown>

- :material-chart-line: **Statistical rigor**

  ---

  Run multi-iteration experiments with bootstrap confidence intervals instead of single-run guesswork.

- :material-recycle-variant: **Reproducibility by design**

  ---

  Use seed control, setup/teardown isolation, and full environment capture for defensible results.

- :material-file-chart: **Publication-quality output**

  ---

  Generate ECDF plots, CI error bars, and paper-ready reports with colorblind-safe visual defaults.

- :material-compare-horizontal: **Apples-to-apples comparison**

  ---

  Benchmark the exact same workload across drivers, ORMs, and language stacks.

- :material-timer-outline: **High-fidelity latency tracking**

  ---

  Record latency distributions with an HDR histogram implementation tuned for benchmark workloads.

- :material-cog-sync: **Scenario-driven workflows**

  ---

  Encode workload, load profile, experiment controls, and targets in one versionable YAML scenario.

</div>

## Quick Install

```bash
pip install benchforge
```

Then follow the [Quick Start guide](quickstart.md) to run your first benchmark and generate a report.

## Why BenchForge?

Most benchmark scripts are ad-hoc and difficult to reproduce. BenchForge is purpose-built for trustworthy comparisons:

- Multi-iteration measurements with statistical confidence
- Controlled experiment design via scenario DSL
- Repeatable runs with deterministic seed behavior
- Result artifacts designed for both academic and engineering review

If you are new to BenchForge, start with [Quick Start](quickstart.md), then read [Concepts](concepts.md) and [Methodology](methodology.md).
