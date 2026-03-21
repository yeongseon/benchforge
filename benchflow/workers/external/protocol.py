"""External worker protocol — JSON contract between benchflow runner and subprocess workers.

Any language can implement an external worker by reading an input JSON config file
and writing a result JSON to stdout. This module defines the Pydantic models for both sides.

## Subprocess Lifecycle

1. Runner writes ``WorkerInput`` to a temporary JSON file.
2. Runner spawns: ``<command> <config_path>``
3. The external process reads the config, runs the benchmark, and writes
   ``WorkerOutput`` as a single JSON object to **stdout**.
4. Runner parses stdout JSON and maps it to ``TargetResult``.

## Implementing an External Worker (any language)

Read the JSON file whose path is passed as the first CLI argument.
Execute the benchmark according to the config, then print a single JSON
object to stdout matching the ``WorkerOutput`` schema below.

### Input schema (WorkerInput)

```json
{
  "dsn": "cubrid://dba:@localhost:33000/benchdb",
  "steps": [
    {"name": "select-by-pk", "query": "SELECT ... WHERE id = ?", "params": {"id": "random_int(1,100)"}}
  ],
  "concurrency": 4,
  "duration_s": 15,
  "warmup_s": 3,
  "seed": 42,
  "setup_queries": ["CREATE TABLE ..."],
  "teardown_queries": ["DROP TABLE ..."],
  "worker_config": {}
}
```

### Output schema (WorkerOutput)

```json
{
  "status": "ok",
  "steps": [
    {
      "name": "select-by-pk",
      "ops": 50000,
      "errors": 0,
      "latency_summary": {
        "min_ns": 100000, "max_ns": 5000000,
        "mean_ns": 500000, "stdev_ns": 200000,
        "p50_ns": 450000, "p95_ns": 1200000,
        "p99_ns": 2500000, "p999_ns": 4500000, "p9999_ns": 4900000
      },
      "throughput_ops_s": 5000.0,
      "samples_ns": [100000, 200000],
      "time_series": [
        {"second": 0, "ops": 500, "errors": 0, "p50_ns": 450000, "p95_ns": 1200000, "p99_ns": 2500000}
      ]
    }
  ],
  "duration_s": 15.2,
  "error_message": null,
  "server_info": {"server_version": "11.2.0"}
}
```
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input: benchflow runner → external process
# ---------------------------------------------------------------------------


class WorkerInputStep(BaseModel):
    """A single benchmark step to execute."""

    name: str
    query: str
    params: dict[str, Any] | None = None


class WorkerInput(BaseModel):
    """Configuration passed to external worker process as a JSON file.

    The external process receives the path to this file as its first CLI argument.
    """

    dsn: str
    steps: list[WorkerInputStep]
    concurrency: int = 1
    duration_s: int = 10
    warmup_s: int = 5
    seed: int | None = None
    setup_queries: list[str] = Field(default_factory=list)
    teardown_queries: list[str] = Field(default_factory=list)
    worker_config: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Output: external process → benchflow runner (via stdout)
# ---------------------------------------------------------------------------


class WorkerOutputLatency(BaseModel):
    """Latency summary in nanoseconds."""

    min_ns: int = 0
    max_ns: int = 0
    mean_ns: int = 0
    stdev_ns: int = 0
    p50_ns: int = 0
    p95_ns: int = 0
    p99_ns: int = 0
    p999_ns: int = 0
    p9999_ns: int = 0


class WorkerOutputTimeWindow(BaseModel):
    """Per-second time-series bucket."""

    second: int
    ops: int = 0
    errors: int = 0
    p50_ns: float = 0.0
    p95_ns: float = 0.0
    p99_ns: float = 0.0


class WorkerOutputStep(BaseModel):
    """Result for a single benchmark step."""

    name: str
    ops: int = 0
    errors: int = 0
    latency_summary: WorkerOutputLatency = Field(default_factory=WorkerOutputLatency)
    throughput_ops_s: float = 0.0
    samples_ns: list[int] = Field(default_factory=list)
    time_series: list[WorkerOutputTimeWindow] = Field(default_factory=list)


class WorkerOutput(BaseModel):
    """Result JSON that external workers write to stdout.

    ``status`` must be ``"ok"`` on success.  Any other value (e.g. ``"error"``)
    signals failure; the runner will read ``error_message`` for diagnostics.
    """

    status: str  # "ok" | "error"
    steps: list[WorkerOutputStep] = Field(default_factory=list)
    duration_s: float = 0.0
    error_message: str | None = None
    server_info: dict[str, Any] = Field(default_factory=dict)
