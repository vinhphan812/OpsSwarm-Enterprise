# ADR-011: Skill Artifact Contract, Invocation Schema, and Test Evidence Mapping

**Date:** 2026-09-22
**Status:** APPROVED
**Type:** Architecture Decision
**Scope:** Skills S1-S8 artefact structure, invocation boundaries, and test organization

---

## Summary

This ADR defines the canonical structure for Skill artefacts, their invocation mechanism, and the test evidence mapping
that satisfies GitHub issues #2, #3, and #6 without duplicating runtime logic.

---

## 1. Canonical Per-Skill Machine Resource Shape

### Decision

Each Skill folder contains **only** `SKILL.md`. No scripts/, resources/, or tests/ directories are created under
`skills/sX/`.

```
skills/
├── s1-intent-guard/
│   └── SKILL.md          # Only artefact in skill folder
├── s2-task-graph/
│   └── SKILL.md
├── s3-horizon-plan/
│   └── SKILL.md
├── s4-role-dispatch/
│   └── SKILL.md
├── s5-collab-exec/
│   └── SKILL.md
├── s6-resilience-guard/
│   └── SKILL.md
├── s7-observe-verify/
│   └── SKILL.md
└── s8-orchestration-hub/
    └── SKILL.md
```

### Rationale

- **No duplication:** Runtime logic lives in `opsswarm/skill_logic.py`, not scattered across skill folders
- **Single source of truth:** S1-S8 functions are centralized and importable
- **ADR-006 compliance:** Frontmatter remains minimal (`name` + `description` only)
- **Separation of concerns:** Skill metadata (SKILL.md) vs. implementation (opsswarm/)

---

## 2. Test Discovery and Evidence Mapping

### Decision

Tests for each Skill reside in the **central** `tests/unit/skill_s{1-8}/` directories. This satisfies:

- **Issue #2:** Per-Skill test directories exist (via `tests/unit/skill_sX/`)
- **Issue #3:** 24 substantive tests per Skill without duplicating test logic

```
tests/unit/
├── skill_s1/
│   └── test_parse_issue.py    # S1 tests (24+ cases)
├── skill_s2/
│   └── test_build_tasks.py    # S2 tests
├── skill_s3/
│   └── test_recovery_plan.py  # S3 tests
├── skill_s4/
│   ├── test_execute_task.py   # S4 tests
│   └── test_profile_selection.py
├── skill_s5/
│   └── test_execute_recovery.py
├── skill_s6/
│   └── test_policy_gates.py
├── skill_s7/
│   └── test_verify_recovery.py
└── skill_s8/
    └── test_orchestrator_hub.py
```

### Test Naming Convention

Each test file follows the pattern `test_{function_name}.py` and includes:

- Test ID prefix: `S1-N{n}` (normal), `S1-E{n}` (edge), `S1-Err{n}` (error)
- Docstring describing the scenario and expected outcome
- `@pytest.mark.unit` marker for CI filtering

### Evidence Identity Mapping

| Evidence Type        | Schema                    | Location                               | Producer                             |
|----------------------|---------------------------|----------------------------------------|--------------------------------------|
| S1 parsed incident   | `EV-YYYYMMDDHHMMSSffffff` | `runtime-data/evidence/{run_id}.jsonl` | `evidence.py:EvidenceStore.append()` |
| S2 task graph        | `EV-YYYYMMDDHHMMSSffffff` | Same                                   | `evidence.py`                        |
| S3 recovery plan     | `EV-YYYYMMDDHHMMSSffffff` | Same                                   | `evidence.py`                        |
| S4 findings          | `EV-YYYYMMDDHHMMSSffffff` | Same                                   | `evidence.py`                        |
| S5 execution         | `EV-YYYYMMDDHHMMSSffffff` | Same                                   | `evidence.py`                        |
| S7 verification      | `EV-YYYYMMDDHHMMSSffffff` | Same                                   | `evidence.py`                        |
| S8 state transitions | `EV-YYYYMMDDHHMMSSffffff` | Same                                   | `evidence.py`                        |

---

## 3. Independent Invocation Wrapper Interface

### Decision

Skills are invoked via **direct import** from `opsswarm.skill_logic`. No per-skill wrapper scripts are created.

```python
# S1 invocation
from opsswarm import skill_logic as S
incident = S.parse_issue(issue_number, issue_dict)

# S2 invocation
tasks = await S.build_tasks(oc, "incident-manager", run_id, incident)

# S3 invocation
plan = await S.make_recovery_plan(oc, agent, run_id, incident, root_cause, human_inputs)

# S4 invocation
finding = await S.execute_task(oc, profile_agent, run_id, incident, task)

# S5 invocation
result = await S.execute_recovery(oc, agent, run_id, incident, root, option)

# S7 invocation (S8 calls this independently)
verification = await S.verify_recovery(oc, agent, run_id, incident, execution)
```

### Input/Output Mechanism

| Skill | Input                                             | Output               | Failure Codes                       |
|-------|---------------------------------------------------|----------------------|-------------------------------------|
| S1    | `issue_number:int, issue:dict`                    | `IncidentContext`    | Raises on malformed input           |
| S2    | `oc, agent, run_id, incident`                     | `list[Task]`         | Raises if no tasks produced         |
| S3    | `oc, agent, run_id, incident, root, human_inputs` | `RecoveryPlan`       | Raises on LLM failure               |
| S4    | `oc, profile_agent, run_id, incident, task`       | `Finding`            | Raises on execution failure         |
| S5    | `oc, agent, run_id, incident, root, option`       | `ExecutionResult`    | `ExecutionResult.success=False`     |
| S7    | `oc, agent, run_id, incident, execution`          | `VerificationResult` | `VerificationResult.verified=False` |

### Safe Boundary (S8)

S8 (orchestrator) calls S7 (`verify_recovery`) independently. S8 **cannot** bypass S7 verification or override its veto.
This is enforced in `orchestrator.py:_verify()`:

```python
async def _verify(self, run: RunRecord):
    run.verification = await S.verify_recovery(...)
    if not run.verification.verified:
        # S7 veto: issue remains OPEN
        run.error = "Independent recovery verification failed"
        await self._set_state(run, RunState.FAILED)
```

---

## 4. Shared Validation Schema Ownership

### Decision

Validation logic lives in a **central module** `opsswarm/validators.py`, NOT in individual skill folders. This avoids
conflict with any future `scripts/validate_skill.py`.

```
opsswarm/
├── skill_logic.py    # S1-S8 functions
├── orchestrator.py   # S8 control plane
├── models.py         # Pydantic models
├── evidence.py       # Evidence store
├── policy.py         # Policy engine
└── validators.py    # NEW: shared validation schema
```

### Validator Module Contract

```python
# opsswarm/validators.py

class SkillValidator:
    """Validates skill-related inputs and outputs."""
    
    @staticmethod
    def validate_issue(issue: dict) -> list[str]:
        """Validate issue dict, return list of validation errors."""
        errors = []
        if not issue.get("title"):
            errors.append("issue.title is required")
        # ... more checks
        return errors
    
    @staticmethod
    def validate_incident_context(ctx: IncidentContext) -> list[str]:
        """Validate parsed incident context."""
        errors = []
        if not ctx.service or ctx.service == "unknown":
            errors.append("service field is required")
        # ... more checks
        return errors
```

### Conflict Avoidance

- `scripts/validate_skill.py` (future) will **import** from `opsswarm/validators.py`
- No duplication: validation logic lives in one place
- The script wraps validators with CLI-friendly output

---

## 5. Contract Versioning and Migration Rules

### Version Schema

| Component            | Version | Migration Rule                                        |
|----------------------|---------|-------------------------------------------------------|
| SKILL.md frontmatter | 1.0     | No migration needed (ADR-006)                         |
| Evidence schema      | 1.0     | No migration needed (already EV-YYYYMMDDHHMMSSffffff) |
| Validator schema     | 1.0     | Additive only—new fields are optional                 |
| Test contract        | 1.0     | Each skill needs 24+ substantive tests                |

### Migration Rule

- **Additive changes allowed:** New optional fields can be added to validators
- **Breaking changes require ADR:** Any schema change that breaks existing tests requires a new ADR
- **Evidence is append-only:** Evidence entries are never modified; new entries use new schema version

---

## 6. Acceptance Criteria

### For S1-S4 Artifact Tasks

| Criterion                               | Verification                                             |
|-----------------------------------------|----------------------------------------------------------|
| SKILL.md exists                         | `ls skills/s{1-4}*/SKILL.md`                             |
| No scripts/ under skills/               | `find skills/s{1-4} -name scripts -type d` returns empty |
| Tests exist in tests/unit/skill_s{1-4}/ | `ls tests/unit/skill_s{1-4}/`                            |
| 24+ substantive tests per skill         | Count test functions with `test_s{1-4}_*` prefix         |
| Functions importable                    | `from opsswarm.skill_logic import parse_issue`           |

### For S5-S8 Artifact Tasks

| Criterion                               | Verification                                                       |
|-----------------------------------------|--------------------------------------------------------------------|
| SKILL.md exists                         | `ls skills/s{5-8}*/SKILL.md`                                       |
| No scripts/ under skills/               | `find skills/s{5-8} -name scripts -type d` returns empty           |
| S7 verification is independent          | `grep -n "verify_recovery" orchestrator.py` shows independent call |
| S7 veto is enforced                     | `grep -n "if not run.verification.verified" orchestrator.py`       |
| Tests exist in tests/unit/skill_s{5-8}/ | `ls tests/unit/skill_s{5-8}/`                                      |

### For Validator Task

| Criterion                 | Verification                                |
|---------------------------|---------------------------------------------|
| Module exists             | `ls opsswarm/validators.py`                 |
| Imports in skill_logic.py | `grep -n "from.*validators" skill_logic.py` |
| Script wrapper (optional) | `ls scripts/validate_skill.py` (if created) |

---

## 7. Dependencies for Implementation Tasks

### S1-S4 Tasks Depend On

- ADR-011 (this document)
- `opsswarm/skill_logic.py` (existing)
- `opsswarm/models.py` (existing)
- `tests/unit/skill_s{1-4}/` (existing structure)

### S5-S8 Tasks Depend On

- ADR-011 (this document)
- `opsswarm/orchestrator.py` (existing)
- `opsswarm/skill_logic.py` (existing)
- `tests/unit/skill_s{5-8}/` (existing structure)

### Validator Task Depends On

- ADR-011 (this document)
- `opsswarm/models.py` (existing)
- Existing test patterns in `tests/unit/`

---

## 8. Related Documents

| Document                              | Status          |
|---------------------------------------|-----------------|
| ADR-006_SKILL_FRONTMATTER_CONTRACT.md | APPROVED        |
| GAP_ANALYSIS_S1_S8_ARTEFACTS.md       | Source analysis |
| opsswarm/skill_logic.py               | Production code |
| opsswarm/orchestrator.py              | Production code |
| opsswarm/models.py                    | Production code |
| opsswarm/evidence.py                  | Production code |

---

## 9. Validation Checklist

- [x] No runtime logic duplicated under `skills/`
- [x] SKILL.md only artefact per skill folder
- [x] Tests centralized in `tests/unit/skill_sX/`
- [x] 24+ substantive tests per skill achievable
- [x] Direct import invocation (no wrapper scripts)
- [x] S7 independent verification preserved
- [x] S7 veto power preserved
- [x] S8 control-plane authority preserved
- [x] GitHub-only authorization (no write paths for S8)
- [x] Shared validation module ownership defined
- [x] Evidence schema mapping documented

---

**Decision complete.** Implementation-ready schema delivered.
