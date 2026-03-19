"""Integration tests for BenchFlow against a real PostgreSQL instance.

These tests require a running PostgreSQL server. They are skipped automatically
if the BENCHFLOW_TEST_DSN environment variable is not set.

Environment variables:
    BENCHFLOW_TEST_DSN:
        PostgreSQL DSN for psycopg (e.g., postgresql://postgres:postgres@localhost:5432/benchflow)
    BENCHFLOW_TEST_DSN_SQLALCHEMY:
        PostgreSQL DSN for SQLAlchemy (e.g., postgresql+psycopg://postgres:postgres@localhost:5432/benchflow)

In CI, these are provided by the GitHub Actions PostgreSQL service container.
Locally, start PostgreSQL via: docker compose up -d
"""

from __future__ import annotations

import json
import os
import tempfile

import psycopg
import pytest

from benchflow.core.runner.runner import run_benchmark
from benchflow.core.scenario.schema import (
    ExperimentConfig,
    LoadConfig,
    Scenario,
    SetupTeardown,
    Step,
    TargetConfig,
    WarmupConfig,
)

# ---------------------------------------------------------------------------
# Skip entire module if no PostgreSQL is available
# ---------------------------------------------------------------------------

PSYCOPG_DSN = os.environ.get("BENCHFLOW_TEST_DSN", "")
SQLALCHEMY_DSN = os.environ.get("BENCHFLOW_TEST_DSN_SQLALCHEMY", "")

requires_postgres = pytest.mark.skipif(
    not PSYCOPG_DSN,
    reason="BENCHFLOW_TEST_DSN not set — skipping integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _check_postgres_reachable():
    """Verify we can actually connect before running any tests."""
    if not PSYCOPG_DSN:
        pytest.skip("BENCHFLOW_TEST_DSN not set")
    try:
        conn = psycopg.connect(PSYCOPG_DSN, autocommit=True)
        conn.execute("SELECT 1")
        conn.close()
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")


@pytest.fixture(autouse=True)
def _cleanup_tables():
    """Drop test tables after each test to avoid cross-contamination."""
    yield
    if PSYCOPG_DSN:
        try:
            conn = psycopg.connect(PSYCOPG_DSN, autocommit=True)
            conn.execute("DROP TABLE IF EXISTS integ_users CASCADE")
            conn.execute("DROP TABLE IF EXISTS integ_kv CASCADE")
            conn.execute("DROP TABLE IF EXISTS integ_orders CASCADE")
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_scenario(
    *,
    targets: list[TargetConfig] | None = None,
    iterations: int = 1,
    seed: int | None = 42,
    duration: int = 2,
    concurrency: int = 2,
    steps: list[Step] | None = None,
    setup_queries: list[str] | None = None,
    teardown_queries: list[str] | None = None,
) -> Scenario:
    if targets is None:
        targets = [
            TargetConfig(
                name="psycopg-integ",
                stack_id="python+psycopg",
                driver="psycopg",
                dsn=PSYCOPG_DSN,
            )
        ]
    if steps is None:
        steps = [
            Step(
                name="point-select",
                query="SELECT * FROM integ_users WHERE id = %(id)s",
                params={"id": "random_int(1, 1000)"},
            )
        ]
    default_setup = [
        "CREATE TABLE IF NOT EXISTS integ_users (id SERIAL PRIMARY KEY, name VARCHAR(100))",
        "INSERT INTO integ_users (name) SELECT 'user_' || i FROM generate_series(1, 1000) AS i ON CONFLICT DO NOTHING",
    ]
    default_teardown = ["TRUNCATE TABLE integ_users"]

    return Scenario(
        name="integration-test",
        steps=steps,
        load=LoadConfig(
            concurrency=concurrency,
            duration=duration,
            warmup=WarmupConfig(duration=1),
        ),
        experiment=ExperimentConfig(
            iterations=iterations,
            seed=seed,
            pause_between=0.0,
        ),
        setup=SetupTeardown(queries=setup_queries or default_setup),
        teardown=SetupTeardown(queries=teardown_queries or default_teardown),
        targets=targets,
    )


# ---------------------------------------------------------------------------
# Tests: Smoke — basic engine functionality against real PostgreSQL
# ---------------------------------------------------------------------------


@requires_postgres
class TestSmoke:
    """Verify the core engine works end-to-end against a real database."""

    def test_single_iteration_psycopg(self):
        """Single-iteration run with psycopg produces valid results."""
        scenario = _make_scenario(iterations=1)
        result = run_benchmark(scenario)

        assert result.schema_version == 2
        assert len(result.targets) == 1
        assert result.targets[0].stack_id == "python+psycopg"

        step = result.targets[0].steps[0]
        assert step.name == "point-select"
        assert step.ops > 0
        assert step.throughput_ops_s > 0
        assert step.latency_summary.p50_ns > 0
        assert step.latency_summary.p99_ns >= step.latency_summary.p50_ns
        assert step.errors == 0

    def test_multi_iteration_psycopg(self):
        """Multi-iteration run produces iterations, aggregate, and cross-run stats."""
        scenario = _make_scenario(iterations=3)
        result = run_benchmark(scenario)

        assert result.iterations_requested == 3
        assert len(result.iterations) == 3

        # Each iteration should have valid data
        for it in result.iterations:
            assert len(it.targets) == 1
            assert it.targets[0].steps[0].ops > 0

        # Aggregate should exist
        assert len(result.aggregate) == 1
        agg = result.aggregate[0]
        assert agg.iterations_completed == 3
        assert agg.steps[0].ops.mean > 0
        assert agg.steps[0].throughput_ops_s.mean > 0

    def test_time_series_populated(self):
        """Time-series data should be collected in 1-second windows."""
        scenario = _make_scenario(duration=3)
        result = run_benchmark(scenario)

        step = result.targets[0].steps[0]
        assert len(step.time_series) >= 2  # At least 2 seconds of data

        for tw in step.time_series:
            assert tw.second >= 0
            assert tw.ops > 0

    def test_environment_captured(self):
        """Environment info should be populated from real system."""
        scenario = _make_scenario()
        result = run_benchmark(scenario)

        assert result.environment.hostname != ""
        assert result.environment.os != ""
        assert result.environment.cpu_count > 0
        assert result.environment.python_version != ""

    def test_setup_teardown_executes(self):
        """Setup creates table and teardown truncates it."""
        scenario = _make_scenario(
            setup_queries=[
                "CREATE TABLE IF NOT EXISTS integ_kv (k VARCHAR(32) PRIMARY KEY, v TEXT)",
                "INSERT INTO integ_kv (k, v) VALUES ('test', 'value') ON CONFLICT DO NOTHING",
            ],
            teardown_queries=["TRUNCATE TABLE integ_kv"],
            steps=[
                Step(
                    name="kv-lookup",
                    query="SELECT v FROM integ_kv WHERE k = %(k)s",
                    params={"k": "random_choice('test')"},
                )
            ],
        )
        result = run_benchmark(scenario)
        assert result.targets[0].steps[0].ops > 0
        assert result.targets[0].steps[0].errors == 0


# ---------------------------------------------------------------------------
# Tests: Compatibility — multiple drivers on the same workload
# ---------------------------------------------------------------------------


@requires_postgres
class TestCompatibility:
    """Verify both workers produce consistent results on the same workload."""

    @pytest.mark.skipif(
        not SQLALCHEMY_DSN,
        reason="BENCHFLOW_TEST_DSN_SQLALCHEMY not set",
    )
    def test_psycopg_vs_sqlalchemy(self):
        """Both drivers should complete without errors on identical workload."""
        targets = [
            TargetConfig(
                name="psycopg-integ",
                stack_id="python+psycopg",
                driver="psycopg",
                dsn=PSYCOPG_DSN,
            ),
            TargetConfig(
                name="sqlalchemy-integ",
                stack_id="python+sqlalchemy",
                driver="sqlalchemy",
                dsn=SQLALCHEMY_DSN,
            ),
        ]
        scenario = _make_scenario(targets=targets)
        result = run_benchmark(scenario)

        assert len(result.targets) == 2
        for target in result.targets:
            step = target.steps[0]
            assert step.ops > 0, f"{target.stack_id} had zero ops"
            assert step.errors == 0, f"{target.stack_id} had errors"
            assert step.throughput_ops_s > 0, f"{target.stack_id} had zero throughput"

    @pytest.mark.skipif(
        not SQLALCHEMY_DSN,
        reason="BENCHFLOW_TEST_DSN_SQLALCHEMY not set",
    )
    def test_multi_target_multi_iteration(self):
        """Both drivers across multiple iterations should produce aggregate data."""
        targets = [
            TargetConfig(
                name="psycopg-integ",
                stack_id="python+psycopg",
                driver="psycopg",
                dsn=PSYCOPG_DSN,
            ),
            TargetConfig(
                name="sqlalchemy-integ",
                stack_id="python+sqlalchemy",
                driver="sqlalchemy",
                dsn=SQLALCHEMY_DSN,
            ),
        ]
        scenario = _make_scenario(targets=targets, iterations=2)
        result = run_benchmark(scenario)

        assert len(result.iterations) == 2
        assert len(result.aggregate) == 2

        for agg in result.aggregate:
            assert agg.iterations_completed == 2
            assert len(agg.steps) == 1
            assert agg.steps[0].ops.mean > 0


# ---------------------------------------------------------------------------
# Tests: Result artifacts — JSON output correctness
# ---------------------------------------------------------------------------


@requires_postgres
class TestResultArtifacts:
    """Verify result JSON schema and artifact correctness."""

    def test_result_json_serializable(self):
        """Result should serialize to valid JSON without errors."""
        scenario = _make_scenario(iterations=2)
        result = run_benchmark(scenario)

        json_str = result.model_dump_json(indent=2)
        parsed = json.loads(json_str)

        assert parsed["schema_version"] == 2
        assert parsed["scenario"]["name"] == "integration-test"
        assert len(parsed["iterations"]) == 2
        assert len(parsed["aggregate"]) == 1

    def test_result_json_round_trip(self):
        """Result should survive JSON round-trip without data loss."""
        scenario = _make_scenario()
        result = run_benchmark(scenario)

        json_str = result.model_dump_json()
        parsed = json.loads(json_str)

        # Verify key numeric fields survive serialization
        step = parsed["targets"][0]["steps"][0]
        assert isinstance(step["ops"], int)
        assert isinstance(step["throughput_ops_s"], (int, float))
        assert isinstance(step["latency_summary"]["p50_ns"], (int, float))
        assert isinstance(step["latency_summary"]["p99_ns"], (int, float))

    def test_result_written_to_file(self):
        """Result should write to a file and be readable."""
        scenario = _make_scenario()
        result = run_benchmark(scenario)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(result.model_dump_json(indent=2))
            path = f.name

        try:
            with open(path) as f:
                data = json.load(f)
            assert data["schema_version"] == 2
            assert data["targets"][0]["steps"][0]["ops"] > 0
        finally:
            os.unlink(path)

    def test_scenario_signature_stable(self):
        """Same scenario should produce same signature hash."""
        scenario = _make_scenario()
        result1 = run_benchmark(scenario)
        result2 = run_benchmark(scenario)

        assert result1.scenario.signature == result2.scenario.signature
        assert result1.scenario.signature != ""

    def test_histogram_percentiles_ordered(self):
        """Latency percentiles should be monotonically non-decreasing."""
        scenario = _make_scenario(concurrency=4, duration=3)
        result = run_benchmark(scenario)

        lat = result.targets[0].steps[0].latency_summary
        assert lat.min_ns <= lat.p50_ns <= lat.p95_ns <= lat.p99_ns <= lat.max_ns

    def test_seed_recorded_in_result(self):
        """Experiment seed should be recorded in the result."""
        scenario = _make_scenario(seed=12345, iterations=2)
        result = run_benchmark(scenario)

        assert result.experiment_seed == 12345
        assert result.iterations[0].seed == 12345
        assert result.iterations[1].seed == 12346
