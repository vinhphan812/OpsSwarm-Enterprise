# Skill-Gate Validator and CI Evidence Contract Specification

**Date:** 2026-09-22
**Task Reference:** TRIAGE #6: Define Skill validation and competition gate
**Scope:** S1–S8 Skill validation, CI Evidence schema, False-positive policy

---

## 1. Executive Summary

This document defines the deterministic Skill-gate validator and CI evidence contract required to enforce architectural
integrity in the OpsSwarm-Enterprise multi-agent pipeline. It bridges the contract definitions (Issue #2) and test
architecture (Issue #3) into a single, automated, repository-wide compliance gate.

## 2. Skill-Gate Validator (SGV) Design

The SGV is a unified CLI tool (`scripts/validate_skill.py`) that executes in two modes: `static` and `runnable`.

### 2.1 Static Validation (CI: Fast)

- **Frontmatter Check:** Validates `SKILL.md` YAML frontmatter against `docs/SKILL_CONTRACTS_TRIAGE.md` schema (required
  fields: `name`, `skill_level`, `pipeline_phase`, `produces`).
- **Structure Check:** Ensures existence of `tests/`, `scripts/`, `SKILL.md`.
- **Contract Schema Check:** Validates input/output Python model definitions in `opsswarm/models.py` map correctly to
  expected Skill schemas.

### 2.2 Runnable Invocation (CI: Full)

- **Dependency Check:** Validates dependencies listed in `depends_on` exist and have their own valid `SKILL.md`.
- **Cross-Skill Contract Check:** Runs Skill scripts against mock inputs to ensure output artifact JSON matches the
  defined schema.
- **Test Threshold Check:** Enforces minimum test coverage: (Unit + Contract + Integration) >= `SUBSTANTIVE_THRESHOLD` (
  defined per skill in triage).

---

## 3. CI Evidence Contract

To ensure auditability, all CI runs must produce a machine-readable evidence artifact.

### 3.1 Evidence Schema (JSON)

```json
{
	"run_id": "RUN-GH-123-abc",
	"actor": "CI-BOT",
	"timestamp": "2026-09-22T10:00:00Z",
	"skill_validation": {
		"skill_id": "s1-intent-guard",
		"static_pass": true,
		"runnable_pass": true,
		"tests_run": 24,
		"coverage": 0.95,
		"errors": []
	},
	"evidence_refs": ["EV-202609221000000001", "EV-202609221000000002"]
}
```

### 3.2 Evidence Persistence

- Every validation run MUST archive the evidence to `runtime-data/evidence/{run_id}.jsonl`.
- These JSONL files are the ground truth for "Passed CI Gate".

---

## 4. Operational Policies

### 4.1 False-Positive / Ambiguity Policy

1. **Validator Errors:** Any validator failure breaks the build (exit code > 0).
2. **Ambiguity:** If a script outcome is ambiguous (e.g., non-deterministic output), it MUST be explicitly marked in the
   evidence artifact with `status: "ambiguous"` and `reason: "..."`.
3. **S7 Boundary:** S7 verification results are the _only_ source of truth for "Resolved" status. Orchestrator-side
   assertions are _not_ permitted to override lack of S7 verification.

### 4.2 Test Count Semantics

- **Substantive Threshold:**
    - S1-S8: Minimum 24 tests per Skill (8 normal, 6 boundary, 8 fault, 2 cross-skill).
    - NOTE: All skills use uniform 24-test threshold per Issue #3 mandate.
- **Validation:** SGV fails if `total_tests < SUBSTANTIVE_THRESHOLD`.

---

## 5. Implementation Path

1. **Gate Tooling:** Implement `scripts/validate_skill.py`.
2. **Artifact Definition:** Implement the CI Evidence JSON schema in `opsswarm/models.py`.
3. **CI Integration:** Add `scripts/validate_skill.py --all` to `.github/workflows/test.yml` as a mandatory blocking
   step.
4. **Integration Tests:** Bridge Issue #3 tests into the SGV.

---

## 6. Acceptance Verification

- [ ] SGV implementation exists in `scripts/validate_skill.py`
- [ ] SGV supports --static and --runnable flags
- [ ] CI evidence contract implemented in `opsswarm/evidence.py`
- [ ] Mandatory blocking step in GHA
- [ ] Test threshold enforcement (`SUBSTANTIVE_THRESHOLD`)
- [ ] S7 independence validated by SGV

_End of Spec_
