# Gap Analysis: S1-S8 Operational Artefacts and Authority Contracts

**Task:** t_076bdc59  
**Date:** 2026-09-22  
**Scope:** Reconcile GitHub Issue #2 with skills/s1-intent-guard through skills/s8-orchestration-hub and ADR-006

---

## 1. Executive Summary

This gap analysis identifies what's missing to make each Skill self-contained with operational artefacts (scripts/,
resources/, tests/) while preserving the authority boundaries established in ADR-006.

**Key Finding:** The runtime logic is already implemented in `opsswarm/` modules. The gap is documentation +
self-contained test/validation infrastructure per skill, NOT duplicate runtime code.

---

## 2. Current State (Verified)

### 2.1 Skill Directory Contents

| Skill                | SKILL.md | scripts/ | resources/ | tests/ |
|----------------------|----------|----------|------------|--------|
| s1-intent-guard      | ✓        | ✗        | ✗          | ✗      |
| s2-task-graph        | ✓        | ✗        | ✗          | ✗      |
| s3-horizon-plan      | ✓        | ✗        | ✗          | ✗      |
| s4-role-dispatch     | ✓        | ✗        | ✗          | ✗      |
| s5-collab-exec       | ✓        | ✗        | ✗          | ✗      |
| s6-resilience-guard  | ✓        | ✗        | ✗          | ✗      |
| s7-observe-verify    | ✓        | ✗        | ✗          | ✗      |
| s8-orchestration-hub | ✓        | ✗        | ✗          | ✗      |

### 2.2 Runtime Implementation Location

| Skill               | Production Logic               | File                                        |
|---------------------|--------------------------------|---------------------------------------------|
| S1 IntentGuard      | parse_issue()                  | opsswarm/skill_logic.py:7-19                |
| S2 TaskGraph        | build_tasks()                  | opsswarm/skill_logic.py:21-23               |
| S3 HorizonPlan      | make_recovery_plan()           | opsswarm/skill_logic.py:32-33               |
| S4 RoleDispatch     | execute_task()                 | opsswarm/skill_logic.py:25-27               |
| S5 CollabExec       | execute_recovery()             | opsswarm/skill_logic.py:35-36               |
| S6 ResilienceGuard  | orchestrator gates + policy.py | opsswarm/orchestrator.py:203-205, policy.py |
| S7 ObserveVerify    | verify_recovery()              | opsswarm/skill_logic.py:38-39               |
| S8 OrchestrationHub | Orchestrator class             | opsswarm/orchestrator.py:24-322             |

### 2.3 ADR-006 Status (APPROVED)

The canonical frontmatter contract is:

```yaml
---
name: <skill-id>
description: <one-line>
---
```

**Rejected fields:** skill_level, pipeline_phase, author, version, depends_on, produces

---

## 3. Gap Analysis

### 3.1 Missing Artefacts by Category

| Category       | Status      | Gap Description                                   |
|----------------|-------------|---------------------------------------------------|
| **scripts/**   | ALL MISSING | No standalone invocation scripts per skill        |
| **resources/** | ALL MISSING | No skill-specific config, schemas, or templates   |
| **tests/**     | ALL MISSING | No skill-specific unit tests in skill directories |

### 3.2 Evidence Identity Schema (IMPLEMENTED)

- **ID Format:** `EV-YYYYMMDDHHMMSSffffff`
- **Storage:** `runtime-data/evidence/{run_id}.jsonl`
- **Producer:** EvidenceStore.append() in opsswarm/evidence.py
- **Consumer:** EvidenceStore.list() in opsswarm/evidence.py

This is already implemented per ADR-006 lines 73-82.

### 3.3 S7/S8 Authority Boundary (PRESERVED)

From orchestrator.py:210-227:

- S7 verification is independent (line 212: `await S.verify_recovery()`)
- S7 has veto power (lines 215-220)
- Failed verification keeps issue OPEN (line 222)
- Free text NEVER authorizes side effects; only `/opsswarm approve <option>` commands (line 95 of ADR-006)

---

## 4. Ownership Slices

### 4.1 Schema Ownership

| Schema               | Owner                   | Location                                       |
|----------------------|-------------------------|------------------------------------------------|
| Frontmatter contract | ADR-006                 | docs/adr/ADR-006_SKILL_FRONTMATTER_CONTRACT.md |
| Evidence identity    | Evidence Store          | opsswarm/evidence.py                           |
| Evidence contract    | Reconciliation Contract | docs/guides/RECONCILIATION_CONTRACT.md         |
| State machine        | RunState enum           | opsswarm/models.py:25-61                       |
| Risk taxonomy        | Risk enum               | opsswarm/models.py:64-68                       |

### 4.2 Source Paths

| Component     | Path                     |
|---------------|--------------------------|
| Skill logic   | opsswarm/skill_logic.py  |
| Orchestration | opsswarm/orchestrator.py |
| Models        | opsswarm/models.py       |
| Evidence      | opsswarm/evidence.py     |
| Policy        | opsswarm/policy.py       |

### 4.3 Dependencies on #3/#6

- **Task #3:** Skill contract implementation - determines who owns the shared schema
- **Task #6:** Test infrastructure - determines test structure per skill

---

## 5. Independent Invocation Adapter Boundaries

### 5.1 Current Python API (skill_logic.py)

Each skill function is directly callable:

```python
from opsswarm import skill_logic as S

# S1
incident = S.parse_issue(123, issue_dict)

# S2
tasks = await S.build_tasks(oc, "agent", run_id, incident)

# S3
plan = await S.make_recovery_plan(oc, agent, run_id, incident, root_cause, human_inputs)

# S4
finding = await S.execute_task(oc, profile_agent, run_id, incident, task)

# S5
result = await S.execute_recovery(oc, agent, run_id, incident, root, option)

# S7
verification = await S.verify_recovery(oc, agent, run_id, incident, execution)
```

### 5.2 Script Delegation Model (MISSING)

No standalone scripts exist. Two options:

1. **Per-skill scripts:** Each skill gets its own CLI entrypoint
2. **Central orchestrator script:** Single entrypoint that routes to skills

---

## 6. Acceptance Criteria

### 6.1 For Each Skill

| Criterion          | Verification Command                                                  |
|--------------------|-----------------------------------------------------------------------|
| SKILL.md exists    | `ls skills/s{1-8}*/SKILL.md`                                          |
| Frontmatter valid  | `python -c "import yaml; yaml.safe_load(open('skills/sX/SKILL.md'))"` |
| Tests exist        | `ls skills/s{1-8}*/tests/` (if created)                               |
| Scripts executable | `ls skills/s{1-8}*/scripts/*.sh` (if created)                         |

### 6.2 Authority Preservation

| Criterion        | Verification                                              |
|------------------|-----------------------------------------------------------|
| S7 independence  | orchestrator.py must call verify_recovery() independently |
| S7 veto power    | Failed verification keeps issue OPEN                      |
| GitHub-only auth | Only `/opsswarm approve` commands authorize side effects  |

---

## 7. Decision Required Before Implementation

### 7.1 Shared Schema Ownership

Before creating implementation tasks, decide:

1. **Schema Location:** Should shared schemas live in:
    - A central `schemas/` directory, OR
    - `docs/guides/RECONCILIATION_CONTRACT.md` (current), OR
    - `docs/adr/ADR-006_*` files (current)

2. **Test Location:** Should skill-specific tests live in:
    - `skills/sX/tests/` (per-skill), OR
    - `tests/unit/test_skill_*.py` (central), OR
    - Both (per-skill for integration, central for unit)

3. **Script Entry Points:** Should each skill have its own CLI:
    - `skills/sX/scripts/invoke.py`, OR
    - Use `opsswarm/skill_logic.py` directly

### 7.2 Non-Overlapping Ownership

The following must not overlap:

- Frontmatter parsing (ADR-006 owner)
- Evidence schema (evidence.py owner)
- Test structure (depends on Task #6)
- Script delegation (depends on Task #3)

---

## 8. Related Documents

| Document                              | Status          |
|---------------------------------------|-----------------|
| ADR-006_SKILL_FRONTMATTER_CONTRACT.md | APPROVED        |
| SKILL_CONTRACTS_TRIAGE.md             | Source analysis |
| RECONCILIATION_CONTRACT.md            | Active guide    |
| orchestrator.py                       | Production code |
| skill_logic.py                        | Production code |
| models.py                             | Production code |

---

## 9. Verification Commands

```bash
# Verify all SKILL.md files exist
for i in 1 2 3 4 5 6 7 8; do ls skills/s$i-*/SKILL.md; done

# Verify no scripts/ directories exist
for i in 1 2 3 4 5 6 7 8; do ls -d skills/s$i-*/scripts/ 2>/dev/null && echo "FOUND" || echo "MISSING"; done

# Verify runtime logic location
ls opsswarm/skill_logic.py opsswarm/orchestrator.py opsswarm/models.py

# Verify evidence implementation
grep -n "EV-" opsswarm/evidence.py | head -5

# Verify S7/S8 boundary
grep -n "verify_recovery\|S7.veto\|S7" opsswarm/orchestrator.py
```

---

## 10. Output

This analysis supports creating implementation tasks after Task #3 (shared schema ownership) is resolved.

**Analysis complete.** Ready for implementation task creation.
