# Skill Contracts Triage Report

**Date:** 2026-09-22
**Task:** TRIAGE #2: Define production-grade S1-S8 Skill contracts
**Source:** https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/2

---

## 1. Executive Summary

This document specifies the canonical Skill-contract schema for OpsSwarm's S1-S8 incident response pipeline. It
provides:

- Common frontmatter schema for all Skills
- Per-Skill input/output contracts
- Evidence requirements and authorization boundaries
- Ambiguity handling rules
- Cross-Skill handoff specifications
- Mapping of each Skill to production logic

**Key Finding:** The S8/S7 boundary (OrchestrationHub vs ObserveVerify) is the critical authority boundary that must not
regress.

---

## 2. Current Inventory

### 2.1 Skill Folders

| Skill | Folder                         | Current Description                                  | Production Logic                                         |
|-------|--------------------------------|------------------------------------------------------|----------------------------------------------------------|
| S1    | `skills/s1-intent-guard/`      | Normalize GitHub Issue into bounded incident context | `opsswarm/skill_logic.parse_issue()`                     |
| S2    | `skills/s2-task-graph/`        | Create bounded read-only investigation DAG           | `opsswarm/skill_logic.build_tasks()`                     |
| S3    | `skills/s3-horizon-plan/`      | Produce evidence-supported remediation options       | `opsswarm/skill_logic.make_recovery_plan()`              |
| S4    | `skills/s4-role-dispatch/`     | Dispatch bounded tasks to OpenClaw specialists       | `opsswarm/skill_logic.execute_task()` (via orchestrator) |
| S5    | `skills/s5-collab-exec/`       | Aggregate results and execute authorized recovery    | `opsswarm/skill_logic.execute_recovery()`                |
| S6    | `skills/s6-resilience-guard/`  | Handle failures, ambiguity, human gates              | `opsswarm/orchestrator` (gates) + `opsswarm/policy.py`   |
| S7    | `skills/s7-observe-verify/`    | Independently verify customer/business recovery      | `opsswarm/skill_logic.verify_recovery()`                 |
| S8    | `skills/s8-orchestration-hub/` | Own incident lifecycle and checkpoints               | `opsswarm/orchestrator.py` class                         |

### 2.2 Production Entrypoints

| Module       | File                       | Purpose                    |
|--------------|----------------------------|----------------------------|
| Orchestrator | `opsswarm/orchestrator.py` | S8 workflow control        |
| Skill Logic  | `opsswarm/skill_logic.py`  | S1-S7 execution            |
| Models       | `opsswarm/models.py`       | All data structures        |
| Policy       | `opsswarm/policy.py`       | Risk classification engine |
| Prompts      | `opsswarm/prompts.py`      | LLM prompts per skill      |
| Evidence     | `opsswarm/evidence.py`     | Run artifact storage       |
| Config       | `opsswarm/config.py`       | Configuration loader       |

---

## 3. Common Skill Contract Schema

### 3.1 Frontmatter (Required)

```yaml
---
name: <skill-id> # e.g., s1-intent-guard
description: <one-line> # Canonical purpose
skill_level: S1|S2|S3|S4|S5|S6|S7|S8
pipeline_phase: triage|investigation|planning|execution|verification|control
author: opsswarm-team
version: 1.0.0
depends_on: [] # Skill IDs this depends on
produces: <artifact-type> # e.g., IncidentContext, Task[], RecoveryPlan
---
```

### 3.2 Input Schema (Common Fields)

Every Skill MUST receive:

| Field               | Type            | Required | Description                                  |
|---------------------|-----------------|----------|----------------------------------------------|
| `run_id`            | string          | Yes      | Unique run identifier (e.g., RUN-GH-123-abc) |
| `issue_number`      | integer         | Yes      | GitHub issue number                          |
| `incident`          | IncidentContext | Yes      | Parsed incident context (S1+)                |
| `previous_artifact` | object          | No       | Output from previous Skill                   |
| `human_inputs`      | array           | No       | Human-provided context                       |
| `authority_context` | object          | Yes      | Permission level, approved options           |

### 3.3 Output Schema (Common Fields)

Every Skill MUST produce:

| Field | Type | Required | Description |
| --------------- | ------ | -------- | ------------------------------------- | ------- | --------- |
| `artifact_kind` | string | Yes | e.g., S2.task_graph, S3.recovery_plan |
| `artifacts`     | object | Yes | Skill-specific output |
| `evidence_refs` | array | Yes | List of evidence IDs used |
| `confidence`    | float | No | Confidence score 0-1 |
| `status`        | string | Yes | success | blocked | ambiguous |
| `next_action`   | string | No | Recommended next skill |

### 3.4 Evidence Requirements

- **Required:** Every skill output MUST cite evidence IDs from `EvidenceStore`
- **Format:** `EV-YYYYMMDDHHMMSSffffff` (timestamp-based)
- **Storage:** `runtime-data/evidence/{run_id}.jsonl`
- **Rule:** Never fabricate evidence. Tools must return actual observations.

### 3.5 Authorization Boundaries

| Skill | Read-Only    | Safe Write | Risky Write | Destructive |
|-------|--------------|------------|-------------|-------------|
| S1    | ✓            | -          | -           | -           |
| S2    | ✓            | -          | -           | -           |
| S3    | ✓            | -          | -           | -           |
| S4    | ✓            | -          | -           | -           |
| S5    | -            | ✓          | Policy gate | DENY        |
| S6    | ✓            | Gate only  | Gate only   | -           |
| S7    | ✓            | -          | -           | -           |
| S8    | Control only | -          | -           | -           |

**Critical Rule:** Free text in GitHub comments NEVER authorizes side effects. Only `/opsswarm approve <option>`
commands carry authority.

---

## 4. Per-Skill Implementation Contracts

### S1: IntentGuard

**Phase:** Triage
**Function:** `opsswarm.skill_logic.parse_issue(number, issue)`

| Input                           | Output          |
|---------------------------------|-----------------|
| GitHub Issue (raw API response) | IncidentContext |

**Output Schema:**

```python
IncidentContext(
    issue_number: int,
    title: str,
    body: str,
    service: str,
    environment: str,
    severity: str,  # SEV1-SEV5 or UNKNOWN
    symptoms: list[str],
    customer_impact: str,
    source: str = "github",
    actor: str | None,
    labels: list[str]
)
```

**Constraints:**

- Extract only; never infer missing facts
- Use GitHub Issue as system of record
- Parse severity from labels (`sev:X`)

---

### S2: TaskGraph

**Phase:** Investigation
**Function:** `opsswarm.skill_logic.build_tasks(oc, agent, run_id, incident)`

| Input           | Output     |
|-----------------|------------|
| IncidentContext | list[Task] |

**Output Schema:**

```python
Task(
    id: str,
    type: TaskType,  # OBSERVE, INVESTIGATE, DIAGNOSE
    objective: str,
    profile: str,   # OpenClaw profile name
    required_capabilities: list[str],
    risk: Risk = Risk.READ,
    depends_on: list[str],
    parallelizable: bool,
    expected_output: str,
    status: str
)
```

**Constraints:**

- Only OBSERVE, INVESTIGATE, DIAGNOSE tasks (no REMEDIATE)
- All tasks must be read-only (`risk = "read"`)
- Support parallel execution via `depends_on`
- Use profiles: observability, application, infrastructure, database

---

### S3: HorizonPlan

**Phase:** Planning
**Function:** `opsswarm.skill_logic.make_recovery_plan(oc, agent, run_id, incident, root_cause, human_inputs)`

| Input                                            | Output       |
|--------------------------------------------------|--------------|
| IncidentContext, RootCauseArtifact, human_inputs | RecoveryPlan |

**Output Schema:**

```python
RecoveryPlan(
    options: list[RemediationOption],
    recommended_option: str | None,
    confidence: float,
    requires_business_input: bool,
    business_input_question: str | None
)

RemediationOption(
    id: str,
    description: str,
    profile: str = "recovery-responder",
    risk: Risk,  # read, safe_write, risky_write, destructive
    estimated_recovery: str | None,
    rationale: str,
    capabilities: list[str]
)
```

**Constraints:**

- Each option MUST have risk classification
- If business constraints missing, set `requires_business_input = true`
- Destructive only when truly destructive

---

### S4: RoleDispatch

**Phase:** Investigation (parallel)
**Function:** `opsswarm.skill_logic.execute_task(oc, profile_agent, run_id, incident, task)`

| Input                  | Output  |
|------------------------|---------|
| IncidentContext + Task | Finding |

**Output Schema:**

```python
Finding(
    task_id: str,
    finding: str,
    evidence: list[str],  # EvidenceStore references
    hypothesis: str | None,
    confidence: float,
    recommended_next_action: str | None,
    raw: dict
)
```

**Constraints:**

- Execute only the assigned task scope
- Use actual tool observations, never fabricate
- Profile choices: observability-investigator, application-investigator, infrastructure-investigator,
  database-investigator

---

### S5: CollabExec

**Phase:** Execution
**Function:** `opsswarm.skill_logic.execute_recovery(oc, agent, run_id, incident, root_cause, option)`

| Input                                                 | Output          |
|-------------------------------------------------------|-----------------|
| IncidentContext, RootCauseArtifact, RemediationOption | ExecutionResult |

**Output Schema:**

```python
ExecutionResult(
    option_id: str,
    success: bool,
    summary: str,
    evidence: list[str],
    ambiguous: bool,
    raw: dict
)
```

**Constraints:**

- Execute ONLY the authorized option
- Never broaden scope
- If outcome ambiguous after write, set `ambiguous = true` and DO NOT retry blindly
- Requires policy or explicit `/opsswarm approve` command

---

### S6: ResilienceGuard

**Phase:** Gates (integrated in orchestrator)
**Function:** `opsswarm.policy.PolicyEngine.action(risk)`

| Gate Type        | Trigger                                   | Action                                    |
|------------------|-------------------------------------------|-------------------------------------------|
| WAITING_APPROVAL | Single risky option, policy requires auth | Block until `/opsswarm approve`           |
| WAITING_DECISION | Multiple materially different options     | Block until `/opsswarm approve <id>`      |
| WAITING_INPUT    | Missing business/operational knowledge    | Block until `/opsswarm provide <context>` |

**Ambiguity Handling:**

- Ambiguous write state → S5 sets `ambiguous = true` → Block for human decision
- Never blind-retry ambiguous writes
- Route undecidable states to GitHub Issue comments

---

### S7: ObserveVerify

**Phase:** Verification
**Function:** `opsswarm.skill_logic.verify_recovery(oc, agent, run_id, incident, execution)`

| Input                            | Output             |
|----------------------------------|--------------------|
| IncidentContext, ExecutionResult | VerificationResult |

**Output Schema:**

```python
VerificationResult(
    verified: bool,
    summary: str,
    evidence: list[str],  # Independent evidence only
    confidence: float,
    raw: dict
)
```

**Constraints:**

- **INDEPENDENT verification:** Do not accept executor's success claim as proof
- Use read-only service health evidence: metrics, health checks, logs
- If verification fails, issue remains OPEN
- Confidence threshold: configurable (default 0.85)

---

### S8: OrchestrationHub

**Phase:** Control (entire lifecycle)
**Class:** `opsswarm.orchestrator.Orchestrator`

**Responsibilities:**

- Own incident lifecycle state machine
- Coordinate S1-S7 execution sequence
- Manage human gates
- Handle GitHub comment commands

**State Machine:**

```
OPEN → TRIAGE → INVESTIGATING → DIAGNOSED → PLANNING → EXECUTING → VERIFYING → RESOLVED
         ↓           ↓              ↓            ↓            ↓            ↓
      FAILED    WAITING_INPUT  WAITING_APPROVAL  WAITING_DECISION  FAILED
```

**Critical Rule:** S8 MUST NOT override S7 verification. S7 is independent authority.

---

## 5. Cross-Skill Handoffs

### 5.1 Data Flow

```
S1 (parse_issue)
   ↓ IncidentContext
S2 (build_tasks)
   ↓ list[Task]
S4 (execute_task x N in parallel)
   ↓ list[Finding]
S3 (make_recovery_plan)
   ↓ RecoveryPlan
S5 (execute_recovery) [if authorized]
   ↓ ExecutionResult
S7 (verify_recovery)
   ↓ VerificationResult
S8 (close issue)
```

### 5.2 Handoff Contract

Each handoff MUST include:

1. **Artifact kind:** e.g., `S2.task_graph`
2. **Evidence references:** List of `EV-*` IDs
3. **Confidence score:** 0-1 float
4. **Next action:** Explicit recommendation

### 5.3 Error Propagation

| Error Type          | Handler | Action               |
|---------------------|---------|----------------------|
| Task graph cycle    | S2      | Raise RuntimeError   |
| All tasks failed    | S8      | Transition to FAILED |
| RCA uncertain       | S3      | Request human input  |
| Policy denies       | S6      | Block with reason    |
| Ambiguous write     | S5      | Block for decision   |
| Verification failed | S7      | Keep issue OPEN      |

---

## 6. S8/S7 Authority Boundary (CRITICAL)

**Requirement:** The S8→S7 boundary MUST NOT regress.

### Current Implementation

```
orchestrator.py:_verify():
    run.verification = await S.verify_recovery(...)
    if not run.verification.verified or confidence < threshold:
        run.error = "Independent recovery verification failed"
        await self._set_state(run, RunState.FAILED)
        # Issue remains OPEN
```

### Boundary Rules

1. **S7 is independent:** S8 cannot bypass S7 verification
2. **S7 has veto power:** Failed verification keeps issue OPEN
3. **S7 evidence is read-only:** Uses independent health checks, not executor claims
4. **No regression allowed:** Any change must preserve S7 independence

---

## 7. Required Scripts/Resources/Tests Tree

### Proposed Structure

```
skills/
├── s1-intent-guard/
│   ├── SKILL.md           # Contract definition
│   ├── tests/
│   │   ├── test_parse_issue.py
│   │   └── test_incident_context.py
│   └── scripts/
│       └── validate_issue.py
├── s2-task-graph/
│   ├── SKILL.md
│   ├── tests/
│   │   ├── test_build_tasks.py
│   │   └── test_task_dag.py
│   └── scripts/
│       └── validate_dag.py
├── s3-horizon-plan/
│   ├── SKILL.md
│   ├── tests/
│   │   └── test_recovery_plan.py
│   └── scripts/
│       └── classify_risk.py
├── s4-role-dispatch/
│   ├── SKILL.md
│   ├── tests/
│   │   └── test_execute_task.py
│   └── scripts/
│       └── validate_profile.py
├── s5-collab-exec/
│   ├── SKILL.md
│   ├── tests/
│   │   └── test_execute_recovery.py
│   └── scripts/
│       └── validate_authorization.py
├── s6-resilience-guard/
│   ├── SKILL.md
│   ├── tests/
│   │   ├── test_policy_gates.py
│   │   └── test_ambiguity.py
│   └── scripts/
│       └── simulate_human_gates.py
├── s7-observe-verify/
│   ├── SKILL.md
│   ├── tests/
│   │   ├── test_verify_recovery.py
│   │   └── test_independence.py
│   └── scripts/
│       └── validate_verification.py
└── s8-orchestration-hub/
    ├── SKILL.md
    ├── tests/
    │   ├── test_orchestrator.py
    │   └── test_state_machine.py
    └── scripts/
        └── simulate_full_run.py
```

---

## 8. Architectural Decisions Requiring Approval (ADRs)

### ADR-001: Skill Frontmatter Schema

**Decision:** Adopt YAML frontmatter with required fields (`name`, `skill_level`, `pipeline_phase`, `produces`)
**Status:** Requires approval

### ADR-002: Evidence Store Format

**Decision:** JSONL format with timestamp-based IDs (`EV-YYYYMMDDHHMMSSffffff`)
**Status:** Requires approval

### ADR-003: Human Authority Parsing

**Decision:** Only first line of GitHub comment parsed; only `/opsswarm` commands carry authority
**Status:** Requires approval (from ARCHITECTURE.md)

### ADR-004: S7 Independence Guarantee

**Decision:** S7 verification cannot be bypassed by S8; verification failure keeps issue OPEN
**Status:** Requires approval

### ADR-005: Ambiguity Handling

**Decision:** Ambiguous write state blocks execution; blind retry prohibited
**Status:** Requires approval

---

## 9. Recommendations

1. **Implement SKILL.md expansion** for all 8 skills with full frontmatter and schemas
2. **Add test scaffolding** per skill with mock objects
3. **Create integration tests** for cross-skill handoffs
4. **Document S8/S7 boundary** in architecture as immutable
5. **Create ADR documents** for each decision requiring approval

---

## 10. Acceptance Verification

- [x] All 8 Skill folders inventoried
- [x] Production entrypoints mapped (orchestrator.py, skill_logic.py, models.py, prompts.py)
- [x] S8/S7 boundary documented as critical
- [x] Common contract schema defined
- [x] Per-Skill contracts specified
- [x] Cross-Skill handoffs defined
- [x] Proposed tests tree outlined
- [x] ADRs identified

---

_End of Report_
