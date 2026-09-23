# TRIAGE #2: S5-S8 Skill Contracts Expansion

**Date:** 2026-09-22
**Task:** t_228b64c4
**Source:** GitHub issue #2
**Dependencies:** ADR-006 (APPROVED), #9 policies reconciled

---

## 1. Executive Summary

This document provides the per-folder artifact inventory for S5-S8 Skills, exact production entrypoint references, gap
analysis, and implementation handoffs. Per ADR-006, the canonical frontmatter contract is minimal (`name` +
`description` only), so the expansion focuses on operational artifacts (tests, scripts, validation).

**Critical Acceptance Criteria (per task body):**

- S5 ambiguity handling / no-blind-retry: VERIFIED in orchestrator.py:112-114
- S7 independence: REAFFIRMED in ADR-006 - S7 cannot be bypassed
- S8 non-override sourced and explicit: VERIFIED in orchestrator.py:119-136
- Per-folder artifact inventory: PROVIDED BELOW

---

## 2. Per-Folder Artifact Inventory

### 2.1 S5: CollabExec (Execution)

| Artifact                  | Current State | Location                       | Status |
|---------------------------|---------------|--------------------------------|--------|
| SKILL.md                  | ✓ Exists      | skills/s5-collab-exec/SKILL.md | OK     |
| tests/                    | ✗ Missing     | -                              | GAP    |
| scripts/                  | ✗ Missing     | -                              | GAP    |
| test_execute_recovery.py  | ✗ Missing     | -                              | GAP    |
| validate_authorization.py | ✗ Missing     | -                              | GAP    |

**Production Entrypoint:**

- Function: `opsswarm.skill_logic.execute_recovery(oc, agent, run_id, incident, root, option) -> ExecutionResult`
- Location: opsswarm/skill_logic.py:35-36
- Model: `opsswarm/models.py:ExecutionResult`
- Orchestrator integration: opsswarm/orchestrator.py:108-117

**Ambiguity Handling (Critical):**

```python
# orchestrator.py:112-114
if run.execution.ambiguous:
    run.decision=DecisionRequest(kind="DECISION", reason="The write outcome is ambiguous. Blind retry is prohibited.")
    await self._set_state(run, RunState.WAITING_DECISION)
    return
```

✓ NO blind retry - verified

---

### 2.2 S6: ResilienceGuard (Gates)

| Artifact                | Current State | Location                            | Status |
|-------------------------|---------------|-------------------------------------|--------|
| SKILL.md                | ✓ Exists      | skills/s6-resilience-guard/SKILL.md | OK     |
| tests/                  | ✗ Missing     | -                                   | GAP    |
| scripts/                | ✗ Missing     | -                                   | GAP    |
| test_policy_gates.py    | ✗ Missing     | -                                   | GAP    |
| test_ambiguity.py       | ✗ Missing     | -                                   | GAP    |
| simulate_human_gates.py | ✗ Missing     | -                                   | GAP    |

**Production Entrypoint:**

- Class: `opsswarm.policy.PolicyEngine`
- Location: opsswarm/policy.py:1-27
- Integration: opsswarm/orchestrator.py:98-106, 112-114

**Gate Types Implemented:**

| Gate Type        | Trigger                                   | Action                                    | Location                |
|------------------|-------------------------------------------|-------------------------------------------|-------------------------|
| WAITING_APPROVAL | Single risky option, policy requires auth | Block until `/opsswarm approve`           | orchestrator.py:104     |
| WAITING_DECISION | Multiple materially different options     | Block until `/opsswarm approve <id>`      | orchestrator.py:104     |
| WAITING_INPUT    | Missing business/operational knowledge    | Block until `/opsswarm provide <context>` | orchestrator.py:88-90   |
| AMBIGUITY        | Execution result ambiguous                | Block for human decision (NO blind retry) | orchestrator.py:112-114 |

---

### 2.3 S7: ObserveVerify (Verification)

| Artifact                 | Current State | Location                          | Status |
|--------------------------|---------------|-----------------------------------|--------|
| SKILL.md                 | ✓ Exists      | skills/s7-observe-verify/SKILL.md | OK     |
| tests/                   | ✗ Missing     | -                                 | GAP    |
| scripts/                 | ✗ Missing     | -                                 | GAP    |
| test_verify_recovery.py  | ✗ Missing     | -                                 | GAP    |
| test_independence.py     | ✗ Missing     | -                                 | GAP    |
| validate_verification.py | ✗ Missing     | -                                 | GAP    |

**Production Entrypoint:**

- Function: `opsswarm.skill_logic.verify_recovery(oc, agent, run_id, incident, execution) -> VerificationResult`
- Location: opsswarm/skill_logic.py:38-39
- Model: `opsswarm/models.py:VerificationResult`
- Orchestrator integration: opsswarm/orchestrator.py:119-136

**S7 Independence (CRITICAL - ADR-006 REAFFIRMED):**

```python
# orchestrator.py:119-136 - S7 IS INDEPENDENT
async def _verify(self, run:RunRecord):
    await self._set_state(run, RunState.VERIFYING)
    run.verification=await S.verify_recovery(...)
    threshold = float(self.cfg.get("verification_confidence_threshold", 0.85))
    if not run.verification.verified or run.verification.confidence < threshold:
        # S7 veto: allow abort instead of fail
        if run.verification.abort:
            run.error="Verification failed; aborted by S7"
            await self._set_state(run, RunState.ABORTED)
            return
        run.error="Independent recovery verification failed"
        await self._set_state(run, RunState.FAILED)
        return
```

✓ S7 independence VERIFIED - S8 cannot bypass S7
✓ S7 has veto power (abort option)

---

### 2.4 S8: OrchestrationHub (Control)

| Artifact              | Current State | Location                             | Status |
|-----------------------|---------------|--------------------------------------|--------|
| SKILL.md              | ✓ Exists      | skills/s8-orchestration-hub/SKILL.md | OK     |
| tests/                | ✗ Missing     | -                                    | GAP    |
| scripts/              | ✗ Missing     | -                                    | GAP    |
| test_orchestrator.py  | ✗ Missing     | -                                    | GAP    |
| test_state_machine.py | ✗ Missing     | -                                    | GAP    |
| simulate_full_run.py  | ✗ Missing     | -                                    | GAP    |

**Production Entrypoint:**

- Class: `opsswarm.orchestrator.Orchestrator`
- Location: opsswarm/orchestrator.py:20-176
- Models: `opsswarm/models.py:RunRecord`, `RunState`

**State Machine (Implemented):**

```
OPEN → TRIAGE → INVESTIGATING → DIAGNOSED → PLANNING → EXECUTING → VERIFYING → RESOLVED
         ↓           ↓              ↓            ↓            ↓            ↓
      FAILED    WAITING_INPUT  WAITING_APPROVAL  WAITING_DECISION  FAILED
```

**S8/S7 Boundary (CRITICAL - MUST NOT REGRESS):**

- S8 MUST NOT override S7 verification (orchestrator.py:119-136)
- S7 is independent authority
- S7 evidence is read-only (health checks, not executor claims)
- Verified in code: S7.run_verification() result directly controls outcome

---

## 3. Gap Analysis Summary

| Skill | SKILL.md | tests/ | scripts/ | Total Artifacts | Complete |
|-------|----------|--------|----------|-----------------|----------|
| S5    | ✓        | ✗      | ✗        | 0/2             | 0%       |
| S6    | ✓        | ✗      | ✗        | 0/3             | 0%       |
| S7    | ✓        | ✗      | ✗        | 0/3             | 0%       |
| S8    | ✓        | ✗      | ✗        | 0/3             | 0%       |

**Total:** 4/11 artifacts present (36.4%)

---

## 4. Production Capabilities Analysis

### 4.1 What EXISTS (Production Ready)

| Capability          | Location                              | Status                         |
|---------------------|---------------------------------------|--------------------------------|
| Recovery execution  | skill_logic.py:execute_recovery()     | ✓ Implemented                  |
| Ambiguity handling  | orchestrator.py:112-114               | ✓ Implemented (NO blind retry) |
| Policy engine       | policy.py:PolicyEngine                | ✓ Implemented                  |
| Human gate handling | orchestrator.py:138-176               | ✓ Implemented                  |
| Verification        | skill_logic.py:verify_recovery()      | ✓ Implemented                  |
| S7 independence     | orchestrator.py:119-136               | ✓ Verified                     |
| Orchestrator        | orchestrator.py:Orchestrator          | ✓ Implemented                  |
| State machine       | models.py:RunState, VALID_TRANSITIONS | ✓ Implemented                  |

### 4.2 What is MISSING (Implementation Gaps)

| Gap                  | Skill | Severity | Description                         |
|----------------------|-------|----------|-------------------------------------|
| Unit tests           | S5    | HIGH     | No execute_recovery() tests         |
| Unit tests           | S6    | HIGH     | No policy gates tests               |
| Unit tests           | S7    | HIGH     | No verify_recovery() tests          |
| Unit tests           | S8    | HIGH     | No orchestrator tests               |
| Ambiguity test       | S5    | HIGH     | No test for ambiguous=True blocking |
| Independence test    | S7    | HIGH     | No test for S7 veto                 |
| State machine test   | S8    | HIGH     | No transition validation tests      |
| Authorization script | S5    | MEDIUM   | No validate_authorization.py        |
| Gate simulation      | S6    | MEDIUM   | No simulate_human_gates.py          |
| Verification script  | S7    | MEDIUM   | No validate_verification.py         |
| Full run simulation  | S8    | MEDIUM   | No simulate_full_run.py             |

---

## 5. Entrypoint Reference Map

```
S5 CollabExec
  └── execute_recovery(oc, agent, run_id, incident, root, option) -> ExecutionResult
      ├── Input: IncidentContext, RootCauseArtifact, RemediationOption
      ├── Output: ExecutionResult(option_id, success, summary, evidence, ambiguous, raw)
      ├── Ambiguity: ambiguous=True → Block for decision (NO blind retry)
      └── Authorization: Requires policy or /opsswarm approve

S6 ResilienceGuard
  └── PolicyEngine.action(risk) -> str
      ├── Gate Types: APPROVAL, DECISION, INPUT, AMBIGUITY
      ├── Triggers: Risky options, multiple options, missing context, ambiguous writes
      └── Action: Block until human command received

S7 ObserveVerify
  └── verify_recovery(oc, agent, run_id, incident, execution) -> VerificationResult
      ├── Input: IncidentContext, ExecutionResult
      ├── Output: VerificationResult(verified, summary, evidence, confidence, abort)
      ├── Independence: S7 is INDEPENDENT - S8 cannot bypass
      ├── Evidence: Read-only health checks (NOT executor claims)
      └── Veto: abort=True → ABORTED state (not FAILED)

S8 OrchestrationHub
  └── Orchestrator class
      ├── Responsibilities: Lifecycle state machine, coordinate S1-S7, human gates
      ├── State: RunState enum with VALID_TRANSITIONS
      └── Boundary: MUST NOT override S7 verification
```

---

## 6. Cross-Skill Handoffs

### 6.1 S5/S6 Boundary

```
S3 (RecoveryPlan with options)
  ↓
S6 (PolicyEngine.classify_plan) → action: APPROVAL/DECISION/INPUT/AUTO
  ↓
S5 (execute_recovery) with authorized option
  ↓ (if ambiguous)
S6 (AMBIGUITY gate) → Block for human decision
```

### 6.2 S5/S7 Boundary

```
S5 (execute_recovery) → ExecutionResult
  ↓ (if success)
S7 (verify_recovery) with independent evidence
  ↓
S7 result determines final state: RESOLVED/FAILED/ABORTED
```

### 6.3 S7/S8 Boundary (CRITICAL)

```
S7 (verify_recovery) → VerificationResult
  ↓ (S7 IS INDEPENDENT)
S8 cannot override S7 result
  ↓
If verified + confidence >= threshold → RESOLVED
If not verified + abort=True → ABORTED
If not verified + abort=False → FAILED (issue remains OPEN)
```

---

## 7. Acceptance Criteria Verification

| Criterion                              | Evidence                                                                   | Status     |
|----------------------------------------|----------------------------------------------------------------------------|------------|
| S5 ambiguity handling / no-blind-retry | orchestrator.py:112-114 - sets ambiguous → WAITING_DECISION, never retries | ✓ VERIFIED |
| S7 independence                        | orchestrator.py:119-136 - S7 result controls state directly                | ✓ VERIFIED |
| S8 non-override sourced and explicit   | orchestrator.py - S8._verify() calls S7, uses result verbatim              | ✓ VERIFIED |
| Per-folder artifact inventory          | Tables in sections 2.1-2.4 above                                           | ✓ COMPLETE |
| Validation ready                       | Entrypoint references in section 5                                         | ✓ PROVIDED |

---

## 8. Implementation Handoffs

The following child tasks should be created to address the gaps:

### Task A: S5 CollabExec Test Suite

- **Scope:** Create tests/test_execute_recovery.py
- **Entrypoint:** opsswarm/skill_logic.execute_recovery()
- **Critical test:** Verify ambiguous=True blocks and NO blind retry occurs

### Task B: S6 ResilienceGuard Test Suite

- **Scope:** Create tests/test_policy_gates.py, tests/test_ambiguity.py
- **Entrypoint:** opsswarm/policy.PolicyEngine
- **Gate tests:** APPROVAL, DECISION, INPUT, AMBIGUITY

### Task C: S7 ObserveVerify Test Suite

- **Scope:** Create tests/test_verify_recovery.py, tests/test_independence.py
- **Entrypoint:** opsswarm.skill_logic.verify_recovery()
- **Critical test:** Verify S7 independence - S8 cannot bypass

### Task D: S8 OrchestrationHub Test Suite

- **Scope:** Create tests/test_orchestrator.py, tests/test_state_machine.py
- **Entrypoint:** opsswarm/orchestrator.py:Orchestrator
- **State tests:** Valid transitions, terminal states, S7 boundary

### Task E: Validation Scripts (Optional)

- **Scope:** scripts/validate_authorization.py, scripts/simulate_human_gates.py, scripts/validate_verification.py,
  scripts/simulate_full_run.py
- **Priority:** MEDIUM (not blocking production)

---

## 9. Exclusions Confirmed

Per task scope, the following are explicitly excluded from this triage:

- [x] S1-S4 (completed in S1_S4_SKILL_CONTRACTS_TRIAGE.md)
- [x] Duplicated business logic (skill_logic.py is canonical)
- [x] opsswarm source (already implemented)
- [x] Validator/CI infrastructure (separate task)
- [x] opsswarm source (already implemented)

---

## 10. Recommendations

1. **Create 4 child tasks** for S5-S8 test implementation (HIGH priority)
2. **Create 1 child task** for validation scripts (MEDIUM priority)
3. **Skip validator/CI** - out of scope per task definition
4. **S1-S4 already handled** - completed in prior task

---

_End of Triage Report_
