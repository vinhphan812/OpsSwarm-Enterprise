# Static Analysis Staged Rollout - Issue #71, re-opened by Issue #124

**Status:** Stage-2 baselines are versioned artefacts and are enforced by CI.
**Baseline measured on:** the `origin/master` tree at `32418533`.

---

## Current baseline

| Tool | Scope / configuration | Recorded count |
|------|-----------------------|---------------:|
| Ruff | `opsswarm/ tests/`, rule selection `E,F,I,B,RUF` | **883** |
| mypy | `opsswarm/`, semantic categories enabled, per-module waivers | **0** |
| Bandit | HIGH severity in `opsswarm/` | **0** |

The counts live in `.static_analysis_baseline.toml`. That file is a **required
CI input**: both gate scripts exit non-zero when it is missing, so it must
never be deleted, renamed or excluded from the repository.

- The Ruff count comes from the JSON diagnostic output, not from parsing the
  human-readable output, so the number is stable.
- The mypy count is measured without the incremental cache and with the
  analysis platform pinned to `linux` in `pyproject.toml`. Pinning the platform
  matters: without it mypy resolves `fcntl` versus `msvcrt` differently on the
  developer workstation and on the Linux CI runner, and the gate becomes flaky.

---

## Delta policy

The recorded counts are **ceilings, not targets**.

- A pull request that keeps every count at or below the recorded value passes.
- A pull request that increases any count fails CI.
- Lowering a count is always welcome. Lower it in the same commit as the change
  that caused the reduction, so the baseline never drifts from reality.

To lower a count deliberately, fix the findings, then update
`.static_analysis_baseline.toml` in the same commit.

---

## Local commands

```bash
python scripts/check_ruff_full.py      # Ruff Stage-2 gate
python scripts/check_mypy_strict.py     # mypy Stage-2 gate
make lint                              # fast Stage-1 Ruff gate
make typecheck                         # fast Stage-1 mypy gate
make test                              # unit and contract layers
make ci                                # lint + typecheck + coverage + build
```

Both Stage-2 gates exit `0` when the counts are within the baseline, `1` when
a count is exceeded or the baseline is missing, and `2` when the tool itself
could not run or the baseline is malformed.

---

## Stage 1 - CI gate infrastructure (complete)

- [x] `scripts/check_ruff_full.py` enforces the Ruff Stage-2 baseline.
- [x] `scripts/check_mypy_strict.py` enforces the mypy Stage-2 baseline.
- [x] `.static_analysis_baseline.toml` is a versioned, current baseline record.
- [x] The GitHub Actions quality job invokes both gates and keeps the fast
      Stage-1 checks.
- [x] `tests/unit/test_static_analysis_gate_failures.py` proves the gates
      actually fail, rather than only asserting that the configuration file
      mentions the right values.

## Stage 2 - Ruff Stage-2 baseline (enforced)

**Goal:** keep the enforceable rule set `E,F,I,B,RUF` across `opsswarm/` and
`tests/` from increasing while the debt is reduced.

**How the count is measured:**

```bash
python -m ruff check opsswarm/ tests/ --select=E,F,I,B,RUF --output-format=json
```

**How to reduce it.** The highest-value and lowest-risk targets first:

| Code | Count | Meaning |
|------|------:|---------|
| `F401` | 89 | imported but unused |
| `F841` | 52 | local variable assigned but never used |
| `I001` | 107 | unsorted imports |
| `E501` | 253 | line longer than 100 characters |

`ruff check --select=E,F,I,B,RUF --fix` resolves 297 of the findings
automatically and safely. Review the result before committing: the fix touches
import order and semicolon removal across roughly a hundred files.

**Waivers.** Do not raise the count to absorb new findings. A waiver needs a
reviewable rationale, approval in the pull request, and a baseline update only
when the finding is intentionally accepted.

## Stage 3 - mypy semantic categories (enforced)

The broad global `disable_error_code` list has been removed. Every mypy
semantic category is now enabled by default, and the remaining waivers are
narrowly scoped per module in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = "opsswarm.evidence"
disable_error_code = ["arg-type", "assignment", "attr-defined", "operator", "return-value", "union-attr", "valid-type"]
```

Each waiver names the reason the finding is still outstanding. The modules that
still carry a waiver are `auth`, `cli`, `config`, `evidence`, `ha_db`,
`markdown`, `metrics`, `orchestrator`, `reconciliation`, `registry`,
`skill_logic`, `store`, `tool_allowlist` and `validators`. The safety-critical
modules `models`, `policy`, `github_client` and `openclaw` carry **no waiver
at all**: they are fully type-checked under every semantic category.

**Policy:** `python scripts/check_mypy_strict.py` fails if the count increases.
Reduce findings incrementally; do not silently widen module exceptions. Each
waiver must identify the unresolved reason, be reviewed, and have a sunset plan.

**How to remove a waiver.** Fix the underlying finding first, then delete the
corresponding category from the module override. The gate proves the result.

## Stage 4 - full coverage (backlog)

- Remove the remaining per-module mypy waivers one module at a time.
- Enable the remaining Ruff rule families beyond `E,F,I,B,RUF`.
- Address the remaining type-annotation debt in `metrics.py` and `evidence.py`.

---

## Error-code reference

### Ruff

| Code | Meaning | Stage |
|------|---------|-------|
| `E9` | Syntax and runtime errors | Stage 1 (active) |
| `F63` | Pyflakes stub errors | Stage 1 (active) |
| `F7` | Pyflakes errors | Stage 1 (active) |
| `F82` | Undefined names | Stage 1 (active) |
| `E,F,I,B,RUF` | Stage 2 (active); baseline 883; no increases |

### mypy

| Code | Meaning | Stage |
|------|---------|-------|
| Semantic categories | Enabled globally, waived per module; baseline 0; no increases |

---

## CI integration

`.github/workflows/ci.yml` runs, in order:

```yaml
- name: Lint
  run: python -m ruff check .

- name: Check formatting
  run: python -m ruff format --check opsswarm/commands.py opsswarm/policy.py opsswarm/webhook.py

- name: Type check
  run: python -m mypy

- name: Ruff Stage-2 baseline
  run: python scripts/check_ruff_full.py

- name: mypy Stage-2 baseline
  run: python scripts/check_mypy_strict.py
```

The Stage-1 steps stay fast and unchanged. The Stage-2 steps are the enforced
delta gate.
