# CI Contract — Required Merge Gate for `main`

> **Issue:** [#142][issue-142] — CI Canonical Required Checks
> **Enforced on:** `main` branch (branch protection rules)
> **Last updated:** 2026-10-15

---

## Required Status Checks

The following checks must all pass before merging any PR into `main`. These are
configured as **required status checks** in the repository's branch protection
settings for `main`.

| Required check name | Workflow | Purpose |
|---------------------|----------|---------|
| `Repository Hygiene` | [`ci.yml`](workflows/ci.yml) | Fast gate: conflict markers, YAML validity, no committed secrets |
| `API Build & Test` | [`ci.yml`](workflows/ci.yml) | API unit & integration tests, type checking, coverage |
| `API E2E Smoke` | [`ci.yml`](workflows/ci.yml) | End-to-end smoke tests against the API |
| `Web Build & Test` | [`ci.yml`](workflows/ci.yml) | Web build, type checking, unit & coverage |

All four checks **must be required** in branch protection. Do not remove any of
them.

---

## Workflow Architecture

```
.github/workflows/
├── ci.yml          # Top-level merge gate (no path filter) — always runs
├── api.yml         # API CI + Cloud Run deployment (path-filtered)
├── web.yml         # Web CI/CD (path-filtered)
└── conflict-markers.yml  # Backup conflict-marker gate
```

### Why `ci.yml` has no path filter

GitHub branch protection requires a named check to exist for every commit. If a
workflow runs only on a path filter and no matching files change, the named
check is never emitted — creating a **required-check / path-filter deadlock**.

`ci.yml` solves this by:
1. Running on every PR/push with **no path filter**.
2. Conditionally running expensive jobs (API tests, Web tests) only when relevant
   files change.
3. Always running the fast `Repository Hygiene` job (conflict markers, YAML
   validation, secrets scan).

This guarantees a stable set of required check names regardless of which files a
PR touches.

---

## Path → CI Mapping

| File(s) changed | Triggers |
|----------------|----------|
| `apps/api/**`, `services/forecasting/**`, `tests/e2e/**`, `.github/workflows/api.yml` | `API Build & Test`, `API E2E Smoke` |
| `apps/web/**`, `.github/workflows/web.yml` | `Web Build & Test` |
| `contracts/**` | **Both** API and Web CI (shared contract) |
| Any other file (e.g. docs, ADRs) | `Repository Hygiene` only |

### `contracts_changed` output contract

The `detect-changes` job exposes `contracts_changed` as a boolean output.

**`contracts_changed` is `true` only when a file under `contracts/` changes.**
This is intentionally narrow — it represents only genuine API/Web contract or
schema boundary changes, not merely any change to an API or Web surface file.
This distinction matters because consumers of the CI output (dashboards, release
notes, deployment pipelines) need to know whether a schema/API contract was
touched, not just whether either surface happened to be edited.

| Change type | `api_changed` | `web_changed` | `contracts_changed` |
|------------|:---:|:---:|:---:|
| API-only non-contract file | true | false | false |
| Web-only non-contract file | false | true | false |
| Mixed API + Web non-contract | true | true | false |
| Any `contracts/` file | true | true | true |
| `contracts/` + API + Web | true | true | true |

Locally reproduce this with:

```bash
bash .github/scripts/test-change-detector.sh
```

---

## Repository Hygiene Checks

The `Repository Hygiene` job performs:

1. **No conflict markers** — Rejects any commit containing `<<<<<<<`, `=======`,
   or `>>>>>>>` in tracked files (except `.git/MERGE_MSG`).

2. **Workflow YAML validity** — Runs `yamllint --strict` on all
   `.github/workflows/*.yml` files. Catches malformed YAML that would silently
   disable a workflow.

3. **No committed secrets** — Scans for:
   - AWS access key pattern (`AKIA...`)
   - Generic base64-encoded secrets (heuristic)
   - Private key PEM blocks (`-----BEGIN ... PRIVATE KEY-----`)
   - `password="..."` or `api_key="..."` literals
   - Any committed `.env` file

4. **No `.env` files** — Rejects any committed `.env` or `.env.*` file.

---

## API Build & Test

- Python 3.11
- `mypy` type checking
- `pytest` with coverage (branch coverage required)
- Forecast service tests (risk, demand)
- Simulation KPI tests
- Branch coverage threshold enforcement
- Critical-path coverage policy enforcement

**Coverage floor:** ≥ 85% line, ≥ 75% branch (enforced by `check_branch_threshold.py`).

---

## API E2E Smoke

- Fast end-to-end smoke tests in `tests/e2e/`
- Depends on successful `API Build & Test`
- Uses `FakeLlmProvider` (no real LLM calls)

---

## Web Build & Test

- Node.js 20.17
- TypeScript type checking (`tsc --noEmit`)
- Vite production build
- Vitest unit tests
- Vitest coverage

**Prerequisite:** `FIREBASE_API_BASE_URL` repository variable must be set and must
not point to `localhost`.

---

## Adding or Modifying Required Checks

1. Update this document with the new check name and workflow.
2. Update `ci.yml` (or the relevant workflow) with the new job.
3. Update branch protection rules on GitHub to include the new required check.
4. Commit with message referencing issue #142.

---

## Deployments (Post-Merge Only)

Deployments run in separate workflows (`api.yml` `deploy-cloudrun`, `web.yml`
`deploy`) and **do not block merge**. They are gated on `github.ref ==
'refs/heads/main'` and `github.event_name == 'push'` only.

---

## Troubleshooting

### "Required status check not found"

Ensure the job name in the workflow matches exactly what is configured in branch
protection. GitHub requires an **exact name match**.

### "Workflow not running on my PR"

Check that the changed files match the path filters in `api.yml` or `web.yml`.
For shared contract changes (`contracts/**`), both API and Web CI should run.

### "E2E smoke failed but I didn't change API code"

The E2E smoke suite may depend on deployment state. Ensure the base branch's
API is deployed before running E2E smoke locally.

---

[issue-142]: https://github.com/retailtwin/retailtwin-ai/issues/142
