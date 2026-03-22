# Statistical Methodology

BenchForge's statistical methods are designed for research-grade rigor.
This document describes the measurement, recording, and analysis pipeline
so that results can be independently verified and correctly interpreted.

## Latency Measurement

### Clock Source

All latency measurements use `time.perf_counter_ns()` — a monotonic,
nanosecond-resolution clock. This is the highest-resolution timer available
in Python and is not affected by system clock adjustments.

### Measurement Point

Latency is measured **externally** by the runner, not by the worker:

```python
t0 = time.perf_counter_ns()
worker.execute(step)
t1 = time.perf_counter_ns()
latency = t1 - t0  # nanoseconds
```

This captures the full round-trip cost including:
- Driver-level query preparation
- Network round-trip to the database
- Query execution on the server
- Result deserialization

### GC Control

Garbage collection is disabled during the measurement window
(`gc.disable()` / `gc.enable()`) to prevent GC pauses from contaminating
latency measurements. This is standard practice in microbenchmarking.

## HDR Histogram

BenchForge records latencies using an in-house **HDR (High Dynamic Range)
histogram** — a log-linear data structure that provides:

- **O(1) record** — constant-time insertion regardless of value
- **O(1) merge** — constant-time merge across threads and iterations
- **Configurable precision** — relative error bounded by `1 / 2^sub_bucket_bits`
- **Zero external dependencies** — implemented in pure Python

### How It Works

The histogram divides the value range into **major buckets** (powers of 2),
each subdivided into `2^sub_bucket_bits` linear **sub-buckets**:

```
Major bucket 0: [1, 2)       → 2048 sub-buckets
Major bucket 1: [2, 4)       → 1024 sub-buckets (lower half shared)
Major bucket 2: [4, 8)       → 1024 sub-buckets
...
Major bucket k: [2^k, 2^(k+1)) → 1024 sub-buckets
```

With the default 3 significant digits, sub-bucket count is 2048, giving
a worst-case relative error of ~0.1%. For benchmark latencies (typically
microseconds to seconds), this precision far exceeds measurement noise.

### Percentile Computation

Percentiles are computed by linear scan of the flat counts array:

```python
target_count = ceil(q / 100 * total_count)
running = 0
for idx in range(counts_len):
    running += counts[idx]
    if running >= target_count:
        return value_from_linear_index(idx)
```

This is O(buckets) but only runs at report time, not during measurement.

### Mean and Standard Deviation

For mean and stdev, each bucket's contribution uses the **midpoint**
of its value range (value to highest_equivalent) for better accuracy:

```python
mid = (value + highest_equivalent(value)) / 2
total += mid * count
```

## Reservoir Sampling

For ECDF (Empirical Cumulative Distribution Function) plots, BenchForge
maintains a bounded reservoir sample (max 10,000 values) using
**Vitter's Algorithm R**:

1. First 10,000 values are stored directly
2. For value _n_ (where n > 10,000): replace a random element with
   probability `10000 / n`

This produces a statistically representative sample regardless of total
operation count, with bounded memory usage.

## Time-Series Collection

Latencies are also bucketed into **1-second windows** for time-series analysis:

```python
elapsed_ns = t1 - start_ns
second = int(elapsed_ns // 1_000_000_000)
time_buckets[step_name][second].append(latency)
```

Each window records:
- `ops` — number of operations completed
- `errors` — number of errors
- `p50_ns`, `p95_ns`, `p99_ns` — latency percentiles within the window

Time-series data reveals **temporal patterns** (warmup effects, periodic GC,
connection pool behavior) that aggregate statistics obscure.

## Cross-Iteration Statistics

When running multiple iterations (`experiment.iterations > 1`), BenchForge
computes per-step aggregate statistics across iterations:

### Metrics

For each step metric (ops, throughput, p50, p95, p99, p999):

| Statistic | Formula |
|-----------|---------|
| **Mean** | Arithmetic mean of per-iteration values |
| **Stdev** | Sample standard deviation (ddof=1) |
| **CV** | Coefficient of variation: stdev / mean |
| **95% CI** | Bootstrap confidence interval (see below) |

### Why Iteration-Level Aggregation?

Cross-run statistics are computed over **iteration-level metrics**
(e.g., throughput per iteration), **not** by pooling all individual
operations across iterations. This is because:

1. Each iteration is an independent sample
2. Pooling operations ignores between-iteration variance
3. Iteration-level aggregation correctly captures run-to-run variability

This matches the methodology recommended by database benchmarking literature.

## Bootstrap Confidence Intervals

BenchForge uses the **bootstrap percentile method** for confidence intervals:

### Algorithm

1. Given _n_ iteration-level values: [v₁, v₂, ..., vₙ]
2. Draw 10,000 bootstrap resamples (sample with replacement, size _n_)
3. Compute the mean of each resample
4. Sort the 10,000 bootstrap means
5. The 95% CI is the [2.5th percentile, 97.5th percentile] of bootstrap means

### Why Bootstrap?

- **Distribution-free** — makes no assumption about the underlying distribution
- **Works with small samples** — valid even with 3-5 iterations
- **Captures asymmetry** — unlike t-intervals, the CI can be asymmetric

### Reproducibility

When a seed is provided, the bootstrap RNG is seeded identically, producing
the same confidence intervals across runs.

### Single-Iteration Behavior

With only 1 iteration, the CI degenerates to a point (low = high = value).
For meaningful confidence intervals, use at least 3 iterations; 5+ is
recommended for publication-quality results.

## Comparison Analysis

`bench compare` computes ratios between baseline and contender:

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| p50 ratio | contender.p50 / baseline.p50 | < 1.0 = faster |
| p95 ratio | contender.p95 / baseline.p95 | < 1.0 = faster |
| p99 ratio | contender.p99 / baseline.p99 | < 1.0 = faster |
| Throughput ratio | contender.throughput / baseline.throughput | > 1.0 = faster |

### Verdict Thresholds

| p95 Ratio | Verdict |
|-----------|---------|
| ≤ 0.95 | **Faster** — contender is at least 5% faster |
| ≥ 1.05 | **Slower** — contender is at least 5% slower |
| 0.95 < ratio < 1.05 | **Same** — within noise margin |

## Limitations and Caveats

1. **Closed-loop model**: BenchForge drives queries back-to-back (no think time).
   This measures peak throughput, not typical application behavior.

2. **Python GIL**: Concurrent worker threads share the GIL. CPU-bound
   operations may not scale linearly with concurrency. For I/O-bound
   database queries, this is typically not a bottleneck.

3. **Coordinated omission**: Because BenchForge does not inject artificial
   delays, it does not suffer from coordinated omission in the classic
   sense. However, results represent "service time," not "response time"
   under load.

4. **Histogram quantization**: Latency values are quantized to histogram
   bucket boundaries. With 3 significant digits, the worst-case relative
   error is ~0.1%, which is negligible compared to typical measurement noise.

## See Also

- [Core Concepts](concepts.md)
- [Reproducibility Checklist](reproducibility.md)
