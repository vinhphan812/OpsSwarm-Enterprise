# Test Suite

## Structure

| Directory | Runner | Purpose |
|---|---|---|
| `apps/api/tests/` | pytest | FastAPI boundary: health, store reads, inventory, events |
| `apps/web/src/` | Vitest | React components, API client, scene rendering |

## Running tests locally

### API

```bash
cd apps/api
pip install -e ".[dev]"
pytest
```

With coverage:

```bash
pytest --cov=retailtwin_api --cov-report=term --cov-report=xml --cov-branch
# HTML report: pytest --cov=retailtwin_api --cov-report=html
# Open: apps/api/htmlcov/index.html
```

Coverage thresholds are machine-enforced by CI. There are two tiers:

Coverage thresholds are machine-enforced by CI with two tiers:

1. **Repository minimum** — policy floor. Any PR must keep coverage at or above this or CI blocks merge. Required before Foundation Gate #10.
   - API line/statement: **>= 85%** (`fail_under=85` in `pyproject.toml`)
   - API branch: **>= 75%** (checked via `check_branch_threshold.py`)
   - Web line/statement: **>= 85%** (`thresholds.lines=85` in `vite.config.ts`)
   - Web branch: **>= 75%** (`thresholds.branches=75` in `vite.config.ts`)
   - Web functions: **>= 80%** (`thresholds.functions=80` in `vite.config.ts`)
2. **Non-regression floor** — current measured baseline. A PR that drops coverage even if still above the repository minimum must include tracked justification.
   - API line/statement: **89%**
   - API branch: **85%**
   - Web statements/lines: **91%**
   - Web branches: **91%**

See `apps/api/pyproject.toml` `[tool.coverage.run]` for the full omit/include list.
Key exclusions: `.venv/`, `__pycache__/`, `.pytest_cache/`, `__main__.py`.

### Web

```bash
cd apps/web
npm ci
npm test
```

With coverage:

```bash
npm run test:coverage
# Coverage reports: apps/web/coverage/
#   coverage/lcov-report/index.html -- HTML
#   coverage/lcov.info -- LCOV
#   coverage/cobertura-coverage.xml -- Cobertura XML
```

Coverage thresholds are machine-enforced by CI. Both tiers apply to web (see API section for full terminology):

1. **Repository minimum**: lines >= 85%, branches >= 75%, functions >= 80% (enforced by `thresholds.lines=85` / `thresholds.branches=75` / `thresholds.functions=80` in `vite.config.ts`).
2. **Non-regression floor**: lines **91%**, branches **91%** (current measured baseline; any drop requires tracked justification).

The Vitest config (`apps/web/vite.config.ts`) excludes:
- `src/**/*.d.ts` -- type declarations
- `src/**/types.ts` -- type-only modules
- `src/*-env.d.ts` -- ambient environment declarations

### Critical-path modules

When the following modules are implemented they are subject to elevated thresholds
(line >= 90%, branch >= 85%) via explicit per-path `fail_under` or `thresholds`
configuration in the respective project config:

- `guard/decision-context-guard/` -- Decision Context Guard / No-Stale-Commit
- `services/executor/` -- Executor mutation boundary
- `services/twin/` -- Digital Twin mutation paths
- `services/simulation/` -- Simulation Twin
- `services/verifier/` -- Verifier / recovery
- Event idempotency/conflicts (`apps/api/retailtwin_api/events.py`)

**Enforcement policy:** Any PR that adds a new file under one of these paths must
include a `fail_under` or `thresholds` update for that path before merging.
Until those modules exist, the non-regression floor applies to `apps/api` as a
whole.

## CI

Coverage runs in GitHub Actions on every push to `main` and on every pull request
touching the respective application directory:

- `.github/workflows/api.yml` -- Python API
- `.github/workflows/web.yml` -- TypeScript web

Artifacts:
- `api-coverage` -- `coverage.xml` from pytest-cov
- `web-coverage` -- full `coverage/` directory from Vitest

## Policy

- All PRs must keep coverage at or above the non-regression floor.
- Coverage may not decrease without a tracked justification in the PR.
- Coverage decrease below floor blocks merge.
- Critical-path threshold applies to any module that implements DCG, Executor,
  authorization, event idempotency, simulation-vs-live isolation, verifier, or
  rollback logic.
