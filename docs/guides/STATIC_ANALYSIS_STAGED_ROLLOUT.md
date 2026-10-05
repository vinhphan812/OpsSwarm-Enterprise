# Static Analysis Staged Rollout — Issue #71

**Status:** Implementation PR (feat/issue-71-static-analysis-gates)
**Branch:** `origin/master` (SHA `5428526`)

---

## Baseline (origin/master 5428526)

| Tool | Config | Errors |
|------|--------|--------|
| Ruff | `select = ["E9","F63","F7","F82"]` | **0** |
| mypy | `disable_error_code = [arg-type, assignment, ...]` | **0** |

---

## Staged Rollout Plan

### Stage 1 — CI Gate Infrastructure (this PR) ✅

- [x] `scripts/check_ruff_full.py` — enforces Ruff Stage-2 baseline (E,F,I,B,RUF)
- [x] `scripts/check_mypy_strict.py` — advisory mypy Stage-2 check
- [x] `tests/unit/test_static_analysis_baseline.py` — pytest gate tests
- [x] `.static_analysis_baseline.toml` — versioned baseline record
- [ ] GitHub Actions workflow: gate on these scripts + `uv run ruff check` + `uv run mypy`

**Files added:**
- `tests/unit/test_static_analysis_baseline.py`
- `scripts/check_ruff_full.py`
- `scripts/check_mypy_strict.py`

**Files NOT modified in this PR:**
- `pyproject.toml` — staged config changes deferred to subsequent PRs
- `opsswarm/` source files — no style churn introduced at this stage

---

### Stage 2 — Ruff Stage-2 Baseline (follow-up PR)

**Goal:** Record actual error counts for `ruff check --select=E,F,I,B,RUF` after
applying minimal per-file ignores.  Expected ~0-50 errors (mostly style, not correctness).

**Steps:**
1. Run `ruff check opsswarm/ tests/ --select=E,F,I,B,RUF --output-format=concise`
2. Record `error_count` in `.static_analysis_baseline.toml [baseline.ruff]`
3. Add per-file ignores for patterns that cannot be auto-fixed without churn
4. Update `scripts/check_ruff_full.py` `RUFF_SELECT`
5. PR against `master`

**Expected per-file ignores:**
- `opsswarm/__init__.py` → `F403`, `F405` (star re-exports)
- `opsswarm/evidence.py` → `E402` (module-level side-effects)

---

### Stage 3 — mypy Stage-2 (follow-up PR)

**Goal:** Remove `arg-type`, `assignment`, `attr-defined`, `call-arg`, `index`,
`operator`, `return-value`, `union-attr`, `valid-type`, `var-annotated` from
`disable_error_code` for Stage-1 modules (`opsswarm.models`, `opsswarm.policy`,
`opsswarm.registry`).  Expected ~0-63 errors.

**Steps:**
1. Update `pyproject.toml [tool.mypy]` `disable_error_code` to only retain:
   - `import-untyped`
   - `misc`
2. Run `uv run mypy opsswarm/` and record count
3. Fix blocking errors (expected: minimal)
4. Update `.static_analysis_baseline.toml [baseline.mypy]`
5. Update `scripts/check_mypy_strict.py`
6. PR against `master`

---

### Stage 4 — Full Coverage (backlog)

- Remove remaining `disable_error_code` entries across all of `opsswarm/`
- Address remaining type-annotation debt
- Expand Ruff to full rule set with ignore justifications

---

## Error-Code Reference

### Ruff (by category)

| Code | Meaning | Stage |
|------|---------|-------|
| E9   | Syntax / runtime errors | Stage 1 (active) |
| F63  | Pyflakes stub errors | Stage 1 (active) |
| F7   | Pyflakes errors | Stage 1 (active) |
| F82  |未使用的変数 | Stage 1 (active) |
| E,F,I,B,RUF | Full set | Stage 2 |
| ALL  | All rules | Stage 4 |

### mypy (by category)

| Code | Meaning | Stage |
|------|---------|-------|
| Most codes disabled | Current baseline | Stage 1 (active) |
| `import-untyped`, `misc` | Relaxed | Stage 2 |
| All codes | Full strict | Stage 4 |

---

## CI Integration

Add to `.github/workflows/ci.yml`:

```yaml
  ruff-stage1:
    run: uv run ruff check opsswarm/ tests/ --select=E9,F63,F7,F82

  ruff-stage2:
    run: python scripts/check_ruff_full.py

  mypy-stage1:
    run: uv run mypy opsswarm/

  mypy-stage2:
    run: python scripts/check_mypy_strict.py

  bandit:
    run: python -m pytest tests/unit/test_static_analysis_baseline.py::test_bandit_high_severity_baseline -v
```
