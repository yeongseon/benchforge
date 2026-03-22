# Reproducibility Checklist

This document provides a checklist for researchers and engineers who need
to produce benchmark results that are **reproducible, comparable, and
defensible** — whether for academic publication, engineering evaluation,
or performance regression tracking.

## Why Reproducibility Matters

A benchmark result is only as useful as its reproducibility. Without it:
- Reviewers cannot verify your claims
- Colleagues cannot build on your work
- You cannot reliably detect regressions

BenchForge provides the infrastructure for reproducible benchmarks. This
checklist ensures you use it correctly.

---

## Pre-Benchmark Checklist

### 1. Fix the Database State

- [ ] Use `setup` and `teardown` queries to create and reset test data
- [ ] Ensure setup is idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`)
- [ ] Avoid external dependencies on database state (other tables, roles)

```yaml
setup:
  queries:
    - "CREATE TABLE IF NOT EXISTS users (...)"
    - "INSERT INTO users (...) ON CONFLICT DO NOTHING"

teardown:
  queries:
    - "TRUNCATE TABLE users"
```

### 2. Set a Random Seed

- [ ] Always specify `experiment.seed` for reproducible parameter generation
- [ ] Document the seed in your paper/report

```yaml
experiment:
  seed: 42
```

### 3. Run Multiple Iterations

- [ ] Use at least **5 iterations** for publication-quality results
- [ ] Use at least **3 iterations** for engineering evaluation
- [ ] Set `pause_between` to 2-5 seconds to reduce carry-over effects

```yaml
experiment:
  iterations: 5
  seed: 42
  pause_between: 2.0
```

### 4. Warm Up

- [ ] Set warmup duration ≥ 3 seconds to stabilize JIT, connection pools,
      and database caches
- [ ] Warmup is excluded from measurement automatically

```yaml
load:
  warmup:
    duration: 5
```

### 5. Capture Environment

- [ ] Use `--capture-db-info` to record database server configuration
- [ ] BenchForge automatically captures: hostname, OS, CPU, memory, Python version

```bash
bench run scenario.yaml --capture-db-info -v
```

---

## During Benchmarking

### 6. Isolate the System

- [ ] Close unnecessary applications
- [ ] Ensure no other benchmarks or heavy processes are running
- [ ] If using a cloud instance, prefer dedicated hosts over shared VMs
- [ ] Disable CPU frequency scaling if possible (`performance` governor)

### 7. Use Adequate Duration

- [ ] Set `load.duration` to at least **10 seconds** per iteration
- [ ] For latency-sensitive comparisons, use **30+ seconds**
- [ ] Short durations amplify startup transients

### 8. Match Concurrency to Your Question

- [ ] Single-threaded (`concurrency: 1`) for pure driver overhead comparison
- [ ] Multi-threaded (`concurrency: 4-16`) for connection pool / scaling behavior
- [ ] Document your choice and rationale

---

## Post-Benchmark Checklist

### 9. Verify Result Quality

- [ ] Check the CV (coefficient of variation) in aggregate statistics
  - CV < 5% → Excellent stability
  - CV 5-15% → Acceptable
  - CV > 15% → Investigate (system noise, insufficient warmup, etc.)
- [ ] Inspect time-series plots for anomalies (spikes, drift, periodic patterns)
- [ ] Verify that confidence intervals do not overlap (for claims of difference)

### 10. Report Completely

When publishing results, always include:

- [ ] **BenchForge version** (`benchflow.__version__`)
- [ ] **Scenario file** (verbatim, or as an appendix)
- [ ] **Random seed** used
- [ ] **Number of iterations** and pause duration
- [ ] **Environment**: OS, CPU model, memory, Python version
- [ ] **Database**: version, key configuration parameters
- [ ] **Concurrency** and duration per iteration

### 11. Archive Results

- [ ] Save the raw JSON result files (not just the HTML report)
- [ ] Store the exact scenario YAML used
- [ ] Pin BenchForge version in your requirements
- [ ] Consider `CITATION.cff` for citing BenchForge in your paper

---

## Common Pitfalls

| Pitfall | Impact | Fix |
|---------|--------|-----|
| Single-iteration comparison | No confidence intervals, no variance estimate | Use `iterations: 5+` |
| No random seed | Different parameters each run | Set `experiment.seed` |
| No warmup | First-run effects skew results | Set `warmup.duration: 3+` |
| Short duration (< 5s) | Startup transients dominate | Use `duration: 10+` |
| No setup/teardown | Database state drift across iterations | Add setup + teardown |
| Ignoring CV | Publishing unstable results | Check CV < 15% |
| Pooling ops across iterations | Underestimating variance | BenchForge does this correctly by default |
| Missing environment metadata | Results cannot be reproduced | Use `--capture-db-info` |

---

## For Academic Papers

If you are including BenchForge results in a paper:

1. **Cite BenchForge** using the `CITATION.cff` file in the repository
2. **Include the scenario YAML** as a listing or appendix
3. **Report all parameters** (iterations, seed, concurrency, duration, warmup)
4. **Show confidence intervals** — use the aggregate statistics table or CI error bars
5. **Discuss methodology** — reference this document or the [Methodology](methodology.md) page
6. **Archive raw data** — deposit JSON result files in your paper's artifact repository

### Example Reporting

> We evaluated psycopg3 and SQLAlchemy Core using BenchForge v0.1.0 with
> 5 iterations (seed=42), 4 concurrent threads, 10-second measurement
> windows after 3-second warmup, and 2-second pauses between iterations.
> Results show psycopg3 achieves 1.42x higher throughput (95% CI:
> [1.38, 1.46]) and 28% lower p95 latency. Environment: PostgreSQL 16.2
> on Linux 6.5.0 (8-core AMD Ryzen 7, 32 GB RAM, Python 3.12.1).

## See Also

- [Statistical Methodology](methodology.md)
