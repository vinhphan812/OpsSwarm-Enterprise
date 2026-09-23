# TRIAGE #2: S1-S4 Skill Contracts Expansion

**Date:** 2026-09-22
**Task:** t_70580a0f
**Source:** GitHub issue #2
**Dependencies:** ADR-006 (APPROVED)

---

## 1. Executive Summary

This document provides the per-folder artifact inventory for S1-S4 Skills, exact production entrypoint references, gap
analysis, and implementation handoffs. Per ADR-006, the canonical frontmatter contract is minimal (`name` +
`description` only), so the expansion focuses on operational artifacts (tests, scripts, validation).

---

## 2. Per-Folder Artifact Inventory

### 2.1 S1: IntentGuard

| Artifact                 | Current State | Location                        | Status |
|--------------------------|---------------|---------------------------------|--------|
| SKILL.md                 | ✓ Exists      | skills/s1-intent-guard/SKILL.md | OK     |
| tests/                   | ✗ Missing     | -                               | GAP    |
| scripts/                 | ✗ Missing     | -                               | GAP    |
| test_parse_issue.py      | ✗ Missing     | -                               | GAP    |
| test_incident_context.py | ✗ Missing     | -                               | GAP    |
| validate_issue.py        | ✗ Missing     | -                               | GAP    |

**Production Entrypoint:**

- Function: `opsswarm.skill_logic.parse_issue(number:int, issue:dict) -> IncidentContext`
- Location: opsswarm/skill_logic.py:7-19
- Model: `opsswarm/models.py:IncidentContext`

---

### 2.2 S2: TaskGraph

| Artifact            | Current State | Location                      | Status |
|---------------------|---------------|-------------------------------|--------|
| SKILL.md            | ✓ Exists      | skills/s2-task-graph/SKILL.md | OK     |
| tests/              | ✗ Missing     | -                             | GAP    |
| scripts/            | ✗ Missing     | -                             | GAP    |
| test_build_tasks.py | ✗ Missing     | -                             | GAP    |
| test_task_dag.py    | ✗ Missing     | -                             | GAP    |
| validate_dag.py     | ✗ Missing     | -                             | GAP    |

**Production Entrypoint:**

- Function: `opsswarm.skill_logic.build_tasks(oc, agent:str, run_id:str, incident:IncidentContext) -> list[Task]`
- Location: opsswarm/skill_logic.py:21-23
- Model: `opsswarm/models.py:Task`

---

### 2.3 S3: HorizonPlan

| Artifact              | Current State | Location                        | Status |
|-----------------------|---------------|---------------------------------|--------|
| SKILL.md              | ✓ Exists      | skills/s3-horizon-plan/SKILL.md | OK     |
| tests/                | ✗ Missing     | -                               | GAP    |
| scripts/              | ✗ Missing     | -                               | GAP    |
| test_recovery_plan.py | ✗ Missing     | -                               | GAP    |
| classify_risk.py      | ✗ Missing     | -                               | GAP    |

**Production Entrypoint:**

- Function: `opsswarm.skill_logic.make_recovery_plan(oc, agent, run_id, incident, root, human_inputs) -> RecoveryPlan`
- Location: opsswarm/skill_logic.py:32-33
- Models: `opsswarm/models.py:RecoveryPlan`, `RemediationOption`

---

### 2.4 S4: RoleDispatch

| Artifact             | Current State | Location                         | Status |
|----------------------|---------------|----------------------------------|--------|
| SKILL.md             | ✓ Exists      | skills/s4-role-dispatch/SKILL.md | OK     |
| tests/               | ✗ Missing     | -                                | GAP    |
| scripts/             | ✗ Missing     | -                                | GAP    |
| test_execute_task.py | ✗ Missing     | -                                | GAP    |
| validate_profile.py  | ✗ Missing     | -                                | GAP    |

**Production Entrypoint:**

- Function:
  `opsswarm.skill_logic.execute_task(oc, profile_agent:str, run_id:str, incident:IncidentContext, task:Task) -> Finding`
- Location: opsswarm/skill_logic.py:25-27
- Model: `opsswarm/models.py:Finding`

---

## 3. Gap Analysis Summary

| Skill | SKILL.md | tests/ | scripts/ | Total Artifacts | Complete |
|-------|----------|--------|----------|-----------------|----------|
| S1    | ✓        | ✗      | ✗        | 0/4             | 0%       |
| S2    | ✓        | ✗      | ✗        | 0/4             | 0%       |
| S3    | ✓        | ✗      | ✗        | 0/3             | 0%       |
| S4    | ✓        | ✗      | ✗        | 0/3             | 0%       |

**Total:** 4/14 artifacts present (28.5%)

---

## 4. Production Capabilities Analysis

### 4.1 What EXISTS (Production Ready)

| Capability        | Location                            | Status        |
|-------------------|-------------------------------------|---------------|
| Incident parsing  | skill_logic.py:parse_issue()        | ✓ Implemented |
| Task building     | skill_logic.py:build_tasks()        | ✓ Implemented |
| Task execution    | skill_logic.py:execute_task()       | ✓ Implemented |
| Recovery planning | skill_logic.py:make_recovery_plan() | ✓ Implemented |
| Evidence store    | evidence.py:EvidenceStore           | ✓ Implemented |
| Models            | models.py                           | ✓ Implemented |
| Prompts           | prompts.py                          | ✓ Implemented |

### 4.2 What is MISSING (Implementation Gaps)

| Gap                | Skill | Severity | Description                   |
|--------------------|-------|----------|-------------------------------|
| Unit tests         | S1    | HIGH     | No parse_issue() tests        |
| Unit tests         | S2    | HIGH     | No build_tasks() tests        |
| Unit tests         | S3    | HIGH     | No make_recovery_plan() tests |
| Unit tests         | S4    | HIGH     | No execute_task() tests       |
| Validation scripts | S1    | MEDIUM   | No issue structure validator  |
| Validation scripts | S2    | MEDIUM   | No DAG validator              |
| Risk classifier    | S3    | MEDIUM   | No risk classification helper |
| Profile validator  | S4    | MEDIUM   | No OpenClaw profile validator |

---

## 5. Entrypoint Reference Map

```
S1 IntentGuard
  └── parse_issue(number:int, issue:dict) -> IncidentContext
      ├── Input: GitHub API issue response (dict)
      ├── Output: IncidentContext (models.py)
      └── Evidence: EV-* format via EvidenceStore

S2 TaskGraph
  └── build_tasks(oc, agent, run_id, incident) -> list[Task]
      ├── Input: IncidentContext
      ├── Output: list[Task]
      └── Constraints: OBSERVE/INVESTIGATE/DIAGNOSE only (no REMEDIATE)

S3 HorizonPlan
  └── make_recovery_plan(oc, agent, run_id, incident, root, human_inputs) -> RecoveryPlan
      ├── Input: IncidentContext, RootCauseArtifact, human_inputs
      ├── Output: RecoveryPlan with Risk classification
      └── Constraints: Each option must have risk (read/safe_write/risky_write/destructive)

S4 RoleDispatch
  └── execute_task(oc, profile_agent, run_id, incident, task) -> Finding
      ├── Input: IncidentContext + Task
      ├── Output: Finding with evidence refs
      └── Profiles: observability, application, infrastructure, database
```

---

## 6. Implementation Handoffs

The following child tasks should be created to address the gaps:

### Task A: S1 IntentGuard Test Suite

- **Scope:** Create tests/test_parse_issue.py, tests/test_incident_context.py
- **Entrypoint:** opsswarm/skill_logic.parse_issue()
- **Assignee:** dev-reviewer (for test-first implementation)

### Task B: S2 TaskGraph Test Suite

- **Scope:** Create tests/test_build_tasks.py, tests/test_task_dag.py
- **Entrypoint:** opsswarm/skill_logic.build_tasks()
- **Constraints:** Must validate OBSERVE/INVESTIGATE/DIAGNOSE only

### Task C: S3 HorizonPlan Test Suite

- **Scope:** Create tests/test_recovery_plan.py
- **Entrypoint:** opsswarm/skill_logic.make_recovery_plan()
- **Constraints:** Must validate risk classification

### Task D: S4 RoleDispatch Test Suite

- **Scope:** Create tests/test_execute_task.py
- **Entrypoint:** opsswarm/skill_logic.execute_task()
- **Constraints:** Must validate profile selection

### Task E: Validation Scripts (Optional)

- **Scope:** scripts/validate_issue.py, scripts/validate_dag.py, scripts/classify_risk.py, scripts/validate_profile.py
- **Priority:** MEDIUM (not blocking production)

---

## 7. Exclusions Confirmed

Per task scope, the following are explicitly excluded from this triage:

- [x] S5-S8 (out of scope)
- [x] Duplicated business logic (skill_logic.py is canonical)
- [x] opsswarm source (already implemented)
- [x] Validator/CI infrastructure (separate task)

---

## 8. Acceptance Verification

- [x] Per-folder artifact inventory completed (S1-S4)
- [x] Exact entrypoint references documented
- [x] Production capabilities mapped to skill_logic.py
- [x] Missing artifacts identified as gaps
- [x] Implementation handoffs defined
- [x] Exclusions confirmed

---

## 9. Recommendations

1. **Create 4 child tasks** for S1-S4 test implementation (HIGH priority)
2. **Create 1 child task** for validation scripts (MEDIUM priority)
3. **Skip validator/CI** - out of scope per task definition
4. **S5-S8 handled separately** - not in this scope

---

_End of Triage Report_
