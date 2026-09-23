# Skill-Gate Validator Implementation Plan

**Task:** TRIAGE #6: Skill validator and machine-readable gate evidence
**Date:** 2026-09-22
**Status:** Implementation Plan

---

## 1. Threshold Conflict Resolution

### 1.1 The Conflict

| Source                                | S1-S5 | S6-S8 | Total |
|---------------------------------------|-------|-------|-------|
| SKILL_GATE_VALIDATOR_CONTRACT_SPEC.md | 24    | 12    | 156   |
| Issue #3 (mandatory)                  | 24    | 24    | 192   |

### 1.2 Resolution Decision

**ADOPT Issue #3 THRESHOLD**: All 8 skills require 24 tests minimum.

Rationale:

- Issue #3 is the authoritative source for test campaign design
- All 192 tests already exist and pass
- S6-S8 are orchestrator/policy skills where 24 tests ensures state machine coverage
- Uniform 24-test threshold simplifies validator logic

### 1.3 Required SPEC Update

Update `SKILL_GATE_VALIDATOR_CONTRACT_SPEC.md` line 73:

```diff
- S6-S8: Minimum 12 tests per Skill (higher weight on state machine).
+ S6-S8: Minimum 24 tests per Skill (matching Issue #3 mandate).
```

---

## 2. Validator CLI Implementation

### 2.1 Script Location

`scripts/validate_skill.py`

### 2.2 Command Interface

```bash
python scripts/validate_skill.py --skill <skill-id>          # Single skill
python scripts/validate_skill.py --all                       # All skills
python scripts/validate_skill.py --static                    # Fast mode only
python scripts/validate_skill.py --runnable                 # Full mode
python scripts/validate_skill.py --evidence                  # Output evidence JSON
```

### 2.3 Validation Phases

#### Phase 1: Static Validation

| Check               | Description                                 | Fail Action |
|---------------------|---------------------------------------------|-------------|
| SKILL.md exists     | File present in skills/<skill-id>/          | Exit 1      |
| Frontmatter valid   | YAML parses, required fields present        | Exit 1      |
| Required fields     | name, skill_level, pipeline_phase, produces | Exit 1      |
| Directory structure | tests/, SKILL.md exist                      | Exit 1      |

#### Phase 2: Runnable Validation

| Check                 | Description                                 | Fail Action |
|-----------------------|---------------------------------------------|-------------|
| Dependencies valid    | depends_on skills exist with valid SKILL.md | Exit 1      |
| Test count >= 24      | pytest --collect-only count                 | Exit 1      |
| Cross-skill contracts | Output schema matches next skill input      | Exit 1      |

#### Phase 3: Evidence Generation

| Output           | Location                             |
|------------------|--------------------------------------|
| Evidence JSON    | stdout (or file with --evidence)     |
| Evidence archive | runtime-data/evidence/{run_id}.jsonl |

---

## 3. Evidence Model

### 3.1 Evidence Schema (JSON)

```json
{
  "run_id": "SGV-20260922-001",
  "timestamp": "2026-09-22T10:00:00Z",
  "actor": "dev-qa",
  "validation_mode": "static|runnable|all",
  "skills_validated": ["s1-intent-guard", "s2-task-graph", ...],
  "results": [
    {
      "skill_id": "s1-intent-guard",
      "static_pass": true,
      "static_errors": [],
      "runnable_pass": true,
      "runnable_errors": [],
      "tests_collected": 24,
      "tests_passed": 24,
      "coverage": 0.87,
      "cross_skill_valid": true,
      "dependencies_valid": true,
      "evidence_refs": ["EV-202609221000000001"]
    }
  ],
  "overall_pass": true,
  "failures": []
}
```

### 3.2 Evidence Storage

- **Location**: `runtime-data/evidence/{run_id}.jsonl`
- **Format**: JSONL (one line per run)
- **Retention**: Append-only, Git-ignored

### 3.3 Evidence Model Implementation

File: `opsswarm/evidence.py` (exists, needs update)

Required exports:

- `SkillValidationResult` dataclass
- `EvidenceRecord` dataclass
- `save_evidence(record, run_id)` function
- `load_evidence(run_id)` function

---

## 4. Test Discovery Semantics

### 4.1 Discovery Rules

1. **Location**: `tests/unit/skill_{s1-s8}/test_*.py`
2. **Pattern**: `test_*.py` files only
3. **Collection**: `pytest --collect-only -q`
4. **Count**: All collected test items

### 4.2 Category Breakdown (for reporting)

| Category    | Marker                   | Expected |
|-------------|--------------------------|----------|
| Normal      | @pytest.mark.normal      | 8        |
| Boundary    | @pytest.mark.boundary    | 6        |
| Fault       | @pytest.mark.fault       | 8        |
| Cross-Skill | @pytest.mark.cross_skill | 2        |

### 4.3 False-Positive Rules

1. **Ambiguous output**: Mark as `status: "ambiguous"`, reason required
2. **S7 independence**: S7 verification results are sole source of truth
3. **Orchestrator override prohibited**: Cannot assert "passed" without S7 verification

---

## 5. Cross-Skill Boundary Rules

### 5.1 Skill Pipeline

```
S1 (IntentGuard) → S2 (TaskGraph) → S3 (HorizonPlan) → S4 (RoleDispatch)
                          ↓
                   S6 (ResilienceGuard) ← S5 (CollabExec)
                          ↓
                   S7 (ObserveVerify) ← S8 (OrchestrationHub)
```

### 5.2 Contract Validation

- S1 output (IncidentContext) → S2 input validation
- S2 output (TaskList) → S3 input validation
- S3 output (RecoveryPlan) → S4/S5 input validation
- S5 output (ExecutionResult) → S7 input validation
- S7 output (VerificationResult) → S8 state update

### 5.3 Boundary Enforcement

- Validator runs each skill's tests independently
- Cross-skill tests verify contract compatibility
- No circular dependencies allowed

---

## 6. Source Changes Required

### 6.1 New Files

| File                                            | Purpose                               |
|-------------------------------------------------|---------------------------------------|
| `scripts/validate_skill.py`                     | Main validator CLI                    |
| `opsswarm/evidence.py`                          | Evidence model (exists, needs update) |
| `tests/unit/skill_s1/test_cross_skill_s1_s2.py` | Cross-skill tests (if missing)        |

### 6.2 Modifications

| File                                         | Change                                  |
|----------------------------------------------|-----------------------------------------|
| `docs/SKILL_GATE_VALIDATOR_CONTRACT_SPEC.md` | Update S6-S8 threshold to 24            |
| `opsswarm/evidence.py`                       | Add EvidenceRecord, save/load functions |
| `.github/workflows/test.yml`                 | Add validate_skill.py as blocking gate  |

### 6.3 CI Integration

```yaml
# .github/workflows/test.yml addition
- name: Skill Gate Validator
  run: python scripts/validate_skill.py --all --evidence
  env:
    GITHUB_RUN_ID: ${{ github.run_id }}
```

---

## 7. Acceptance Criteria

- [ ] `scripts/validate_skill.py` implemented with --static, --runnable, --all, --evidence flags
- [ ] S6-S8 threshold updated to 24 in SPEC
- [ ] Evidence JSON schema matches specification
- [ ] Evidence saved to runtime-data/evidence/{run_id}.jsonl
- [ ] Test discovery counts all tests in tests/unit/skill_*/
- [ ] Cross-skill boundary validation functional
- [ ] CI gate blocks on validation failure
- [ ] All 192 tests pass individually

---

## 8. Implementation Sequence

1. **Update SPEC** (threshold fix)
2. **Implement evidence model** (opsswarm/evidence.py)
3. **Implement validate_skill.py** (static + runnable phases)
4. **Add test markers** (normal, boundary, fault, cross_skill)
5. **Integrate CI gate** (.github/workflows/test.yml)
6. **Verify** (all 192 tests pass through validator)

---

_End of Implementation Plan_
