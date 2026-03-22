# AGENTS.md

## Purpose
`benchforge` is a research-grade, scenario-based polyglot database benchmark platform for DB researchers and engineers.

## Read First
- `README.md`
- `CONTRIBUTING.md`
- `docs/architecture.md`

## Working Rules
- Runtime code must remain compatible with Python 3.10+.
- Public APIs must be fully typed.
- The CLI surface (`bench run`, `bench compare`, `bench report`) follows semver — breaking changes only in major versions.
- Keep documentation examples, scenario files, and tests synchronized with any behavior changes.
- HDR histogram implementation is zero-dependency by design — do not add external histogram libraries.
- No f-string interpolation in SQL queries — use parameterized queries only.
- Result schema is versioned (currently v2) — changes require a version bump.

## Validation
- `pytest tests/ -v --ignore=tests/integration`
- `ruff check . && ruff format --check .`
- `pyright benchflow/`
- `python -m build`
