# Contributing to BenchFlow

Thank you for considering contributing to BenchFlow! This guide will help you get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/yeongseon/benchflow.git
cd benchflow

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install in development mode
pip install -e ".[dev]"

# Verify installation
bench --help
python -m pytest tests/ -v
```

## Running Tests

```bash
# Run all unit tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_histogram.py -v

# Run with coverage
python -m pytest tests/ --cov=benchflow --cov-report=term-missing
```

### Integration Tests

Integration tests require a running PostgreSQL instance:

```bash
# Start PostgreSQL via Docker Compose
docker compose up -d

# Run integration tests
BENCHFLOW_TEST_DSN="postgresql://postgres:postgres@localhost:5432/benchflow" \
BENCHFLOW_TEST_DSN_SQLALCHEMY="postgresql+psycopg://postgres:postgres@localhost:5432/benchflow" \
python -m pytest tests/integration/ -v

# Stop PostgreSQL
docker compose down
```

## Code Style

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check linting
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Check formatting
ruff format --check .

# Auto-format
ruff format .
```

### Style Rules

- Line length: 100 characters
- Target: Python 3.10+
- Enabled rule sets: `E`, `F`, `I`, `N`, `W`, `UP`

## Adding a New Scenario

1. Create a YAML file in `examples/` (see [Scenario DSL Reference](docs/scenario-reference.md))
2. Include a comment header explaining what the scenario benchmarks and why
3. Test it locally: `bench run examples/your-scenario.yaml -v`
4. Ensure setup/teardown queries are idempotent

## Adding a New Worker

1. Create a new module in `benchflow/workers/`
2. Subclass `Worker` from `benchflow/workers/protocol.py`
3. Implement all abstract methods: `connect()`, `execute()`, `execute_raw()`, `close()`, `introspect()`
4. Register the worker with `@WorkerRegistry.register("driver-name")`
5. Add unit tests in `tests/`
6. Add an example scenario that uses the new driver

## Reporting Benchmark Results

When sharing benchmark results (in issues, papers, or discussions):

- **Always include** the full environment info from the report (CPU, memory, OS, DB version)
- **Always include** the scenario YAML used
- **Always specify** the BenchFlow version and random seed
- **Never compare** results across different hardware without explicit disclaimers
- **Prefer** multi-iteration runs (5+ iterations) with CI error bars over single-run numbers

## Pull Request Guidelines

1. Fork the repository and create a feature branch
2. Ensure all tests pass: `python -m pytest tests/ -v`
3. Ensure linting passes: `ruff check . && ruff format --check .`
4. Write clear commit messages describing the "why" not just the "what"
5. Update documentation if you change user-facing behavior
6. Add tests for new functionality

## Reporting Issues

Use the issue templates provided. For benchmark-related issues, include:

- BenchFlow version (`bench --version`)
- Python version
- OS and hardware info
- Database type and version
- The scenario YAML file used
- The full error output or unexpected behavior description

## License

By contributing to BenchFlow, you agree that your contributions will be licensed under the MIT License.
