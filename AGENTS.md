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

## Issue Scope

- Describe the problem, evidence, proposed work, priority, and completion criteria
  using this repository's own responsibilities and user impact.
- Adapt reusable ideas to the actual files and conventions here. Another
  project's policy, observations, or release plan do not establish this
  repository's requirements.
- Keep relevant technical evidence and source attribution, including actual
  dependencies, integrations, upstream defects, and official documentation.
  Explain the relationship and the work owned by this repository. Apply the
  same local-evidence requirement to explicitly requested comparisons.
- Numerical performance claims need reproducible results, workload, versions,
  and environment details. Label illustrative examples explicitly and do not
  turn an assumed driver comparison into work owned by another project.
- Before creating or editing an issue, search for duplicates and review every
  project name and repository link in the title and body. Remove unrelated
  copied context; the work must be understandable without an unrelated issue.
- After saving, fetch the issue again and verify its title, body, and labels
  before reporting completion. This applies to API and CLI authoring as well
  as the issue templates.

## Validation
- `pytest tests/ -v --ignore=tests/integration`
- `ruff check . && ruff format --check .`
- `pyright benchflow/`
- `python -m build`
