# OpsSwarm S1-S8 Test Campaign Design (192 Tests)

**Task:** TRIAGE #3: Design substantive 192-test Skill campaign  
**Date:** 2026-09-22  
**Source:** https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/3

---

## 1. Overview

This document specifies a non-tautological 24-test campaign for each of the 8 Skills (S1-S8), totaling exactly **192
tests**. The design is derived from actual source code and current documentation, flagging gaps where interfaces are not
fully specified.

### Test Categories

| Category    | Count per Skill | Description                        |
|-------------|-----------------|------------------------------------|
| Normal      | 8               | Happy path, typical inputs         |
| Boundary    | 6               | Edge cases, threshold values       |
| Fault       | 8               | Error conditions, malformed inputs |
| Cross-Skill | 2               | Integration between Skills         |
| **Total**   | **24**          | per Skill                          |

---

## 2. Production Entrypoint Mapping

| Skill | Function                                                                    | File                                     | Parameters                                            |
|-------|-----------------------------------------------------------------------------|------------------------------------------|-------------------------------------------------------|
| S1    | `parse_issue(number, issue)`                                                | `opsswarm/skill_logic.py:7`              | GitHub issue dict                                     |
| S2    | `build_tasks(oc, agent, run_id, incident)`                                  | `opsswarm/skill_logic.py:21`             | OpenClaw client, agent, IncidentContext               |
| S3    | `make_recovery_plan(oc, agent, run_id, incident, root_cause, human_inputs)` | `opsswarm/skill_logic.py:32`             | IncidentContext, RootCauseArtifact                    |
| S4    | `execute_task(oc, profile_agent, run_id, incident, task)`                   | `opsswarm/skill_logic.py:25`             | IncidentContext + Task                                |
| S5    | `execute_recovery(oc, agent, run_id, incident, root_cause, option)`         | `opsswarm/skill_logic.py:35`             | IncidentContext, RootCauseArtifact, RemediationOption |
| S6    | Policy engine gates                                                         | `opsswarm/policy.py` + `orchestrator.py` | Risk classification                                   |
| S7    | `verify_recovery(oc, agent, run_id, incident, execution)`                   | `opsswarm/skill_logic.py:38`             | IncidentContext, ExecutionResult                      |
| S8    | `Orchestrator` class                                                        | `opsswarm/orchestrator.py`               | Full lifecycle                                        |

---

## 3. Existing Reusable Tests

### Currently Available

| File                         | Tests | Coverage                                                                                           |
|------------------------------|-------|----------------------------------------------------------------------------------------------------|
| `tests/test_orchestrator.py` | 4     | S8 end-to-end (safe auto-resolve, approval flow, free text never approves, permission enforcement) |
| `tests/test_issue_parse.py`  | 1     | S1 basic parsing                                                                                   |
| `tests/fakes.py`             | -     | FakeGitHub, FakeOpenClaw for mocking                                                               |
| `tests/test_policy.py`       | 1     | S6 risk classification                                                                             |

### Gap: No existing tests for S2, S3, S4, S5, S7 individually

---

## 4. Per-Skill Test Matrix

### 4.1 S1: IntentGuard

**Phase:** Triage  
**Function:** `parse_issue(number, issue)` → `IncidentContext`  
**Contract:** Extract facts only; never infer missing data

#### Normal (8)

| ID    | Description                        | Input                                             | Expected Output                      |
|-------|------------------------------------|---------------------------------------------------|--------------------------------------|
| S1-N1 | Complete issue with all fields     | Full issue with service, env, symptoms, sev label | All fields parsed correctly          |
| S1-N2 | Minimal issue (title only)         | Issue with just title                             | Default "unknown" for missing fields |
| S1-N3 | Multiple severity labels           | Issue with sev:1 and sev:2                        | Highest severity wins (SEV1)         |
| S1-N4 | Symptoms as multiline              | Body with "### Symptoms\n- error 1\n- error 2"    | List of 2 symptoms                   |
| S1-N5 | Customer impact with special chars | Impact: "Service X is down (90% users)"           | Preserves special chars              |
| S1-N6 | Actor extraction                   | Issue created by "user123"                        | actor = "user123"                    |
| S1-N7 | Labels as strings                  | labels: ["opsswarm", "sev:3"]                     | Parses correctly                     |
| S1-N8 | Empty body                         | Issue with empty body                             | Defaults applied                     |

#### Boundary (6)

| ID    | Description             | Input                               | Expected Output             |
|-------|-------------------------|-------------------------------------|-----------------------------|
| S1-B1 | No ### prefix fields    | Fields without ### marker           | Uses regex fallback         |
| S1-B2 | Whitespace-only fields  | " " for field value                 | Empty string, not "unknown" |
| S1-B3 | Very long field (>10KB) | Giant body                          | Handles without crash       |
| S1-B4 | Invalid severity format | "SEVERE" instead of "sev:X"         | Returns "UNKNOWN"           |
| S1-B5 | Duplicate field names   | "### Service\napi\n### Service\ndb" | First occurrence wins       |
| S1-B6 | Missing body entirely   | body = None                         | Defaults applied            |

#### Fault (8)

| ID    | Description                | Input                           | Expected Output          |
|-------|----------------------------|---------------------------------|--------------------------|
| S1-F1 | Malformed JSON issue       | Issue as string instead of dict | TypeError handled        |
| S1-F2 | None issue object          | issue = None                    | Graceful degradation     |
| S1-F3 | Invalid label format       | Label as integer                | Skips invalid, continues |
| S1-F4 | Regex injection attempt    | Field name with regex chars     | Escaped properly         |
| S1-F5 | Circular reference in body | Body references itself          | No infinite loop         |
| S1-F6 | Unicode-only content       | Body: "🎉🚀🔥"                  | Handles unicode          |
| S1-F7 | Missing title              | title = None                    | Empty string             |
| S1-F8 | Very large symptom list    | 1000+ symptoms                  | Truncates reasonably     |

#### Cross-Skill (2)

| ID    | Description                     | Input                  | Expected Output            |
|-------|---------------------------------|------------------------|----------------------------|
| S1-C1 | Output feeds S2 build_tasks     | Parsed IncidentContext | Valid input to S2          |
| S1-C2 | Output validates against schema | IncidentContext        | Pydantic validation passes |

---

### 4.2 S2: TaskGraph

**Phase:** Investigation  
**Function:** `build_tasks(oc, agent, run_id, incident)` → `list[Task]`  
**Contract:** Read-only DAG; only OBSERVE/INVESTIGATE/DIAGNOSE tasks

#### Normal (8)

| ID    | Description             | Input                       | Expected Output                   |
|-------|-------------------------|-----------------------------|-----------------------------------|
| S2-N1 | Single task DAG         | Simple incident             | 1+ tasks returned                 |
| S2-N2 | Parallel tasks          | Independent evidence needs  | Tasks with `parallelizable=true`  |
| S2-N3 | Sequential dependencies | Dependent investigation     | `depends_on` field populated      |
| S2-N4 | Mixed task types        | OBSERVE + INVESTIGATE       | Correct types assigned            |
| S2-N5 | All profiles used       | Complex incident            | Uses multiple specialist profiles |
| S2-N6 | Empty task list         | Minimal incident            | Error or single OBSERVE task      |
| S2-N7 | Task with capabilities  | Specific investigation need | `required_capabilities` populated |
| S2-N8 | Default risk is read    | Any task                    | `risk = "read"`                   |

#### Boundary (6)

| ID    | Description           | Input                          | Expected Output                 |
|-------|-----------------------|--------------------------------|---------------------------------|
| S2-B1 | Maximum 20 tasks      | Complex incident               | Does not exceed limit           |
| S2-B2 | Circular dependency   | DAG with cycle                 | RuntimeError raised             |
| S2-B3 | Orphan tasks          | Task depending on non-existent | Error raised                    |
| S2-B4 | Self-referencing task | depends_on includes own ID     | Error raised                    |
| S2-B5 | No tasks created      | Empty incident                 | Error: "no investigation tasks" |
| S2-B6 | Profile validation    | Invalid profile name           | Error or default fallback       |

#### Fault (8)

| ID    | Description             | Input                  | Expected Output      |
|-------|-------------------------|------------------------|----------------------|
| S2-F1 | LLM returns non-JSON    | Prompt injection       | JSON decode error    |
| S2-F2 | Missing required fields | Incomplete task JSON   | Validation error     |
| S2-F3 | Invalid TaskType        | Type: "INVALID"        | Validation error     |
| S2-F4 | Invalid Risk value      | Risk: "write"          | Validation error     |
| S2-F5 | OpenClaw timeout        | Agent unresponsive     | Timeout error        |
| S2-F6 | Null incident           | incident = None        | TypeError            |
| S2-F7 | Very long objective     | 10KB objective text    | Truncates or accepts |
| S2-F8 | Duplicate task IDs      | Two tasks with ID="T1" | Error: duplicate ID  |

#### Cross-Skill (2)

| ID    | Description                  | Input                | Expected Output              |
|-------|------------------------------|----------------------|------------------------------|
| S2-C1 | Output feeds S4 execute_task | Task list            | Valid input to S4            |
| S2-C2 | S2→S4 parallel execution     | Multiple ready tasks | Tasks dispatched in parallel |

---

### 4.3 S3: HorizonPlan

**Phase:** Planning  
**Function:** `make_recovery_plan(oc, agent, run_id, incident, root_cause, human_inputs)` → `RecoveryPlan`  
**Contract:** Evidence-supported options; risk classification required

#### Normal (8)

| ID    | Description                   | Input                          | Expected Output                  |
|-------|-------------------------------|--------------------------------|----------------------------------|
| S3-N1 | Single safe option            | Confirmed root cause           | One option with safe_write       |
| S3-N2 | Multiple options              | Ambiguous root cause           | 2+ options with different risks  |
| S3-N3 | Recommended option set        | Clear best option              | `recommended_option` populated   |
| S3-N4 | Business input required       | Missing context                | `requires_business_input = true` |
| S3-N5 | Read-only option only         | No write needed                | Risk = "read" option             |
| S3-N6 | Destructive option classified | Potentially destructive action | Risk = "destructive"             |
| S3-N7 | Confidence score              | Root cause analysis            | 0.0-1.0 confidence               |
| S3-N8 | Empty human_inputs            | No human context               | Works with empty list            |

#### Boundary (6)

| ID    | Description           | Input                        | Expected Output              |
|-------|-----------------------|------------------------------|------------------------------|
| S3-B1 | Maximum 10 options    | Many possible actions        | Does not exceed limit        |
| S3-B2 | All same risk         | Multiple safe_write options  | All classified correctly     |
| S3-B3 | Zero options          | Root cause impossible to fix | Empty options list (allowed) |
| S3-B4 | Missing rationale     | Option without rationale     | Empty string or error        |
| S3-B5 | Very long description | 5KB description text         | Handles without crash        |
| S3-B6 | Capability list empty | No capabilities needed       | Empty list allowed           |

#### Fault (8)

| ID    | Description                       | Input                    | Expected Output            |
|-------|-----------------------------------|--------------------------|----------------------------|
| S3-F1 | Invalid risk classification       | Risk: "UNKNOWN"          | Validation error           |
| S3-F2 | Missing required field            | No description           | Validation error           |
| S3-F3 | Destructive without justification | Destructive action       | Accepted (S3 doesn't deny) |
| S3-F4 | LLM returns malformed JSON        | Prompt injection         | JSON error                 |
| S3-F5 | Null root_cause                   | root_cause = None        | TypeError                  |
| S3-F6 | Confidence > 1.0                  | confidence: 1.5          | Validation error           |
| S3-F7 | Negative confidence               | confidence: -0.1         | Validation error           |
| S3-F8 | Option ID collision               | Two options with same ID | Validation error           |

#### Cross-Skill (2)

| ID    | Description             | Input         | Expected Output   |
|-------|-------------------------|---------------|-------------------|
| S3-C1 | Output feeds S5 execute | RecoveryPlan  | Valid input to S5 |
| S3-C2 | Policy gates applied    | Risky options | S6 policy applied |

---

### 4.4 S4: RoleDispatch

**Phase:** Investigation (parallel)  
**Function:** `execute_task(oc, profile_agent, run_id, incident, task)` → `Finding`  
**Contract:** Bounded task execution; evidence-based findings

#### Normal (8)

| ID    | Description             | Input                        | Expected Output               |
|-------|-------------------------|------------------------------|-------------------------------|
| S4-N1 | Successful OBSERVE task | Task with metrics objective  | Finding with evidence         |
| S4-N2 | Successful INVESTIGATE  | Task with diagnose objective | Hypothesis populated          |
| S4-N3 | Confidence high         | Strong evidence              | confidence >= 0.8             |
| S4-N4 | Confidence low          | Weak evidence                | confidence < 0.5              |
| S4-N5 | Recommended action      | Clear next step              | `recommended_next_action` set |
| S4-N6 | Evidence list populated | Multiple observations        | Evidence array non-empty      |
| S4-N7 | Raw data preserved      | Complex tool output          | `raw` field populated         |
| S4-N8 | Task ID preserved       | Any task                     | Finding.task_id matches       |

#### Boundary (6)

| ID    | Description                 | Input             | Expected Output       |
|-------|-----------------------------|-------------------|-----------------------|
| S4-B1 | Maximum 100 evidence items  | Many observations | Does not exceed limit |
| S4-B2 | Empty evidence              | No observations   | Empty list allowed    |
| S4-B3 | Confidence at 0.0           | No evidence       | 0.0 allowed           |
| S4-B4 | Confidence at 1.0           | Certain finding   | 1.0 allowed           |
| S4-B5 | Very long finding text      | 10KB finding      | Handles without crash |
| S4-B6 | Optional hypothesis missing | No hypothesis     | null/None allowed     |

#### Fault (8)

| ID    | Description             | Input                        | Expected Output             |
|-------|-------------------------|------------------------------|-----------------------------|
| S4-F1 | Tool unavailable        | Requested capability missing | Finding with error evidence |
| S4-F2 | OpenClaw error          | Agent failure                | Exception propagated        |
| S4-F3 | Task out of scope       | Task beyond capability       | Error in finding            |
| S4-F4 | Malformed response      | Non-JSON return              | JSON decode error           |
| S4-F5 | Null incident           | incident = None              | TypeError                   |
| S4-F6 | Invalid profile         | Unknown profile              | Error handling              |
| S4-F7 | Task status not updated | Task without status field    | Status defaults to PENDING  |
| S4-F8 | Duplicate findings      | Same task run twice          | Both findings returned      |

#### Cross-Skill (2)

| ID    | Description                | Input                    | Expected Output                   |
|-------|----------------------------|--------------------------|-----------------------------------|
| S4-C1 | Findings aggregate to S3   | Multiple Finding objects | Valid input to make_recovery_plan |
| S4-C2 | Parallel execution results | Concurrent tasks         | All findings collected            |

---

### 4.5 S5: CollabExec

**Phase:** Execution  
**Function:** `execute_recovery(oc, agent, run_id, incident, root_cause, option)` → `ExecutionResult`  
**Contract:** Execute ONLY authorized option; never broaden scope

#### Normal (8)

| ID    | Description            | Input                     | Expected Output                       |
|-------|------------------------|---------------------------|---------------------------------------|
| S5-N1 | Successful safe_write  | Authorized safe option    | success=true, ambiguous=false         |
| S5-N2 | Success with evidence  | Successful recovery       | Evidence list populated               |
| S5-N3 | Ambiguous outcome      | Write result unclear      | ambiguous=true, success=false         |
| S5-N4 | Failed recovery        | Execution error           | success=false, summary contains error |
| S5-N5 | Option ID preserved    | Any option                | option_id matches input               |
| S5-N6 | Raw output captured    | Complex tool output       | `raw` field populated                 |
| S5-N7 | Summary length         | Normal recovery           | Summary is descriptive                |
| S5-N8 | Empty evidence allowed | Recovery without evidence | Empty list allowed                    |

#### Boundary (6)

| ID    | Description               | Input                | Expected Output               |
|-------|---------------------------|----------------------|-------------------------------|
| S5-B1 | Maximum 50 evidence items | Many recovery steps  | Does not exceed limit         |
| S5-B2 | Very long summary         | 10KB summary         | Handles without crash         |
| S5-B3 | Partial success           | Some steps succeeded | success=false, partial info   |
| S5-B4 | No changes needed         | Read-only "recovery" | success=true, no side effects |
| S5-B5 | Idempotent execution      | Run twice            | Same result both times        |
| S5-B6 | Long-running recovery     | 5+ minute operation  | Timeout handled               |

#### Fault (8)

| ID    | Description          | Input                        | Expected Output                 |
|-------|----------------------|------------------------------|---------------------------------|
| S5-F1 | Unauthorized option  | Option without approval      | Error: not authorized           |
| S5-F2 | Policy denies        | Destructive option           | Error: policy denies            |
| S5-F3 | Tool failure         | Recovery tool error          | success=false, error in summary |
| S5-F4 | Blind retry attempt  | Ambiguous + retry            | MUST NOT retry (forbidden)      |
| S5-F5 | Scope creep          | Action beyond option         | Error: exceeds authorized scope |
| S5-F6 | Null option          | option = None                | TypeError                       |
| S5-F7 | Invalid risk option  | Destructive with DENY policy | Error before execution          |
| S5-F8 | Concurrent execution | Same option run twice        | Proper locking/handling         |

#### Cross-Skill (2)

| ID    | Description            | Input            | Expected Output                |
|-------|------------------------|------------------|--------------------------------|
| S5-C1 | Output feeds S7 verify | ExecutionResult  | Valid input to verify_recovery |
| S5-C2 | Human gate triggered   | Ambiguous result | DecisionRequest created        |

---

### 4.6 S6: ResilienceGuard

**Phase:** Gates (integrated)  
**Function:** Policy engine + orchestrator gates  
**Contract:** Handle failures, ambiguity, human gates

#### Normal (8)

| ID    | Description                 | Input                        | Expected Output           |
|-------|-----------------------------|------------------------------|---------------------------|
| S6-N1 | Read auto-approved          | Option with risk=read        | action = "AUTO"           |
| S6-N2 | Safe write auto-approved    | Option with risk=safe_write  | action = "AUTO"           |
| S6-N3 | Risky requires approval     | Option with risk=risky_write | action = "HUMAN_APPROVAL" |
| S6-N4 | Destructive denied          | Option with risk=destructive | action = "DENY"           |
| S6-N5 | WAITING_APPROVAL state      | Risky option selected        | State transition correct  |
| S6-N6 | WAITING_DECISION state      | Multiple options             | State transition correct  |
| S6-N7 | WAITING_INPUT state         | Missing context              | State transition correct  |
| S6-N8 | Ambiguous triggers decision | Ambiguous execution result   | Blocked for decision      |

#### Boundary (6)

| ID    | Description            | Input                      | Expected Output              |
|-------|------------------------|----------------------------|------------------------------|
| S6-B1 | Exactly at threshold   | confidence = 0.80          | Depends on threshold config  |
| S6-B2 | Multiple risky options | 2+ risky_write options     | Highest risk determines gate |
| S6-B3 | Safe + risky mix       | Options of different risks | Each classified correctly    |
| S6-B4 | Policy not defined     | Unknown risk               | Default behavior             |
| S6-B5 | Permission threshold   | read permission            | Only read allowed            |
| S6-B6 | Approval after wait    | Human approves             | Resumes execution            |

#### Fault (8)

| ID    | Description             | Input                     | Expected Output          |
|-------|-------------------------|---------------------------|--------------------------|
| S6-F1 | DENY overridden         | Human tries to force      | Still denied             |
| S6-F2 | Free text approval      | Comment without /opsswarm | NOT accepted as approval |
| S6-F3 | Insufficient permission | Read-only user approves   | PermissionError          |
| S6-F4 | Ambiguous retry         | Ambiguous + retry attempt | Retry blocked            |
| S6-F5 | Invalid policy config   | Policy as string          | Error handling           |
| S6-F6 | Circular gate           | Gate triggers same gate   | No infinite loop         |
| S6-F7 | Missing policy entry    | No entry for risk         | Default DENY or error    |
| S6-F8 | Concurrent approvals    | Two humans approve        | First wins               |

#### Cross-Skill (2)

| ID    | Description       | Input               | Expected Output                  |
|-------|-------------------|---------------------|----------------------------------|
| S6-C1 | S3→S5 policy gate | RecoveryPlan        | Policy applied before execution  |
| S6-C2 | S5→S6 ambiguity   | Ambiguous execution | Blocked, creates DecisionRequest |

---

### 4.7 S7: ObserveVerify

**Phase:** Verification  
**Function:** `verify_recovery(oc, agent, run_id, incident, execution)` → `VerificationResult`  
**Contract:** Independent verification; read-only evidence

#### Normal (8)

| ID    | Description             | Input                                     | Expected Output            |
|-------|-------------------------|-------------------------------------------|----------------------------|
| S7-N1 | Verified successfully   | Recovery succeeded, service healthy       | verified=true              |
| S7-N2 | Not verified            | Recovery claimed success but service down | verified=false             |
| S7-N3 | Independent evidence    | Health check from different source        | Evidence not from executor |
| S7-N4 | Confidence high         | Strong verification signals               | confidence >= 0.85         |
| S7-N5 | Confidence low          | Weak verification                         | confidence < 0.85          |
| S7-N6 | Evidence list populated | Multiple checks                           | Evidence array non-empty   |
| S7-N7 | Summary descriptive     | Verification result                       | Summary explains result    |
| S7-N8 | Raw data preserved      | Complex check output                      | `raw` field populated      |

#### Boundary (6)

| ID    | Description               | Input                          | Expected Output       |
|-------|---------------------------|--------------------------------|-----------------------|
| S7-B1 | Confidence threshold edge | confidence = 0.85              | Depends on config     |
| S7-B2 | Maximum evidence items    | Many checks                    | Does not exceed limit |
| S7-B3 | Partial verification      | Some metrics good, some bad    | verified=false        |
| S7-B4 | No evidence available     | Cannot verify                  | verified=false        |
| S7-B5 | Service still degraded    | Recovery claimed but SLAs down | verified=false        |
| S7-B6 | Timeout on verification   | Health check timeout           | verified=false        |

#### Fault (8)

| ID    | Description                        | Input                        | Expected Output                 |
|-------|------------------------------------|------------------------------|---------------------------------|
| S7-F1 | Accepts executor claim             | Uses execution evidence only | WRONG - must use independent    |
| S7-F2 | Verifies own claim                 | Uses same tools as executor  | Violation of independence       |
| S7-F3 | Null execution                     | execution = None             | TypeError                       |
| S7-F4 | False positive                     | Service actually down        | Should be caught by evidence    |
| S7-F5 | False negative                     | Service actually up          | Should not happen with evidence |
| S7-F6 | Tool unavailable for verification  | No health check tools        | Should report cannot verify     |
| S7-F7 | Malformed response                 | Non-JSON return              | JSON decode error               |
| S7-F8 | Confidence at 1.0 without evidence | No checks performed          | Should be validated             |

#### Cross-Skill (2)

| ID    | Description           | Input               | Expected Output             |
|-------|-----------------------|---------------------|-----------------------------|
| S7-C1 | Independent from S5   | Verification source | NOT using S5 execution data |
| S7-C2 | S8 respects S7 result | verified=false      | S8 keeps issue OPEN         |

---

### 4.8 S8: OrchestrationHub

**Phase:** Control (entire lifecycle)  
**Class:** `Orchestrator`  
**Contract:** Own incident lifecycle; coordinate S1-S7

#### Normal (8)

| ID    | Description       | Input                     | Expected Output        |
|-------|-------------------|---------------------------|------------------------|
| S8-N1 | Full happy path   | Valid issue, safe option  | RESOLVED state         |
| S8-N2 | Requires approval | Risky option              | WAITING_APPROVAL state |
| S8-N3 | Requires decision | Multiple options          | WAITING_DECISION state |
| S8-N4 | Requires input    | Missing context           | WAITING_INPUT state    |
| S8-N5 | S1→S2 flow        | Issue triggers parse      | IncidentContext passed |
| S8-N6 | S2→S4→S3 flow     | Task execution works      | Findings→RecoveryPlan  |
| S8-N7 | S5→S7→S8 flow     | Execution to verification | Full sequence works    |
| S8-N8 | State transitions | All valid transitions     | Correct state machine  |

#### Boundary (6)

| ID    | Description              | Input                      | Expected Output                |
|-------|--------------------------|----------------------------|--------------------------------|
| S8-B1 | All states reachable     | From OPEN to RESOLVED      | Full lifecycle works           |
| S8-B2 | State machine boundaries | Invalid transition attempt | Error or handled               |
| S8-B3 | Parallel task execution  | Multiple ready tasks       | All complete before next phase |
| S8-B4 | Checkpoint resume        | After approval             | Resumes correctly              |
| S8-B5 | Maximum tasks            | Many tasks                 | Handles without timeout        |
| S8-B6 | Label transitions        | Every state change         | GitHub labels updated          |

#### Fault (8)

| ID    | Description                  | Input                    | Expected Output          |
|-------|------------------------------|--------------------------|--------------------------|
| S8-F1 | S2 produces no tasks         | Empty task list          | RuntimeError             |
| S8-F2 | S4 task fails                | Single task failure      | Task marked FAILED       |
| S8-F3 | Task graph cycle             | Cyclic dependencies      | RuntimeError             |
| S8-F4 | RCA below threshold          | confidence < 0.80        | WAITING_INPUT state      |
| S8-F5 | Verification below threshold | confidence < 0.85        | FAILED state             |
| S8-F6 | GitHub API failure           | Comment fails            | Error handled gracefully |
| S8-F7 | Duplicate run                | Same issue started twice | Returns existing run     |
| S8-F8 | Missing required label       | Issue without opsswarm   | RuntimeError             |

#### Cross-Skill (2)

| ID    | Description               | Input              | Expected Output              |
|-------|---------------------------|--------------------|------------------------------|
| S8-C1 | Full pipeline S1→S7       | Complete incident  | End-to-end works             |
| S8-C2 | Human command integration | /opsswarm commands | Commands processed correctly |

---

## 5. Evidence JSON Schema

All evidence MUST follow this schema:

```json
{
	"$schema": "http://json-schema.org/draft-07/schema#",
	"type": "object",
	"required": ["evidence_id", "run_id", "skill", "timestamp"],
	"properties": {
		"evidence_id": {
			"type": "string",
			"pattern": "^EV-\\d{14}\\d{6}$"
		},
		"run_id": {
			"type": "string",
			"pattern": "^RUN-GH-\\d+-[a-f0-9]+$"
		},
		"skill": {
			"type": "string",
			"enum": ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
		},
		"timestamp": {
			"type": "string",
			"format": "date-time"
		},
		"artifact_kind": {
			"type": "string"
		},
		"data": {
			"type": "object"
		},
		"source": {
			"type": "string",
			"description": "Tool or method that produced evidence"
		},
		"confidence": {
			"type": "number",
			"minimum": 0,
			"maximum": 1
		}
	}
}
```

---

## 6. Test Fixture/Stub Boundaries

### Mockable (Test Fixtures)

| Component          | Can Mock | Why                   |
|--------------------|----------|-----------------------|
| FakeGitHub         | Yes      | No real GitHub needed |
| FakeOpenClaw       | Yes      | No LLM calls needed   |
| IncidentContext    | Yes      | Pydantic model        |
| Task list          | Yes      | Data structure        |
| RecoveryPlan       | Yes      | Data structure        |
| ExecutionResult    | Yes      | Data structure        |
| VerificationResult | Yes      | Data structure        |

### Not Mockable (Requires Integration)

| Component                 | Cannot Mock | Why                            |
|---------------------------|-------------|--------------------------------|
| Regex field parsing       | Partially   | Core S1 logic                  |
| Pydantic validation       | No          | Must validate real schema      |
| State machine transitions | No          | Must verify actual transitions |
| Policy engine logic       | Partially   | Core S6 behavior               |

---

## 7. Sequencing Dependencies

### Test Order (Required)

```
S1 tests (all) → S2 tests (all) → S3 tests (all) → S4 tests (all)
                                                    ↓
                                    S5 tests (depends on S3-S4)
                                                    ↓
                                    S6 tests (depends on S3-S5)
                                                    ↓
                                    S7 tests (depends on S5)
                                                    ↓
                                    S8 tests (depends on all)
```

### Parallelization Opportunities

- S1-N1 through S1-N8 can run in parallel (no shared state)
- S2-N1 through S2-N8 can run in parallel (each uses fresh incident)
- S4 tasks can be parallelized (multiple task executions)
- S7 verification tests can run in parallel

---

## 8. Implementation Slices (Non-Overlapping)

| Slice | Skills | Tests | Implementer             |
|-------|--------|-------|-------------------------|
| 1     | S1     | 24    | Developer with S1 focus |
| 2     | S2     | 24    | Developer with S2 focus |
| 3     | S3     | 24    | Developer with S3 focus |
| 4     | S4     | 24    | Developer with S4 focus |
| 5     | S5     | 24    | Developer with S5 focus |
| 6     | S6     | 24    | Developer with S6 focus |
| 7     | S7     | 24    | Developer with S7 focus |
| 8     | S8     | 24    | Developer with S8 focus |

**Constraint:** Each slice is independent - no two implementers should modify the same test file.

---

## 9. Validation Commands

### Run All Tests

```bash
# Full campaign
pytest tests/ -v --tb=short

# Per-Skill
pytest tests/test_s1_intent_guard.py -v
pytest tests/test_s2_task_graph.py -v
pytest tests/test_s3_horizon_plan.py -v
pytest tests/test_s4_role_dispatch.py -v
pytest tests/test_s5_collab_exec.py -v
pytest tests/test_s6_resilience_guard.py -v
pytest tests/test_s7_observe_verify.py -v
pytest tests/test_s8_orchestration_hub.py -v
```

### Run by Category

```bash
# Normal tests only
pytest tests/ -v -k "N1 or N2 or N3 or N4 or N5 or N6 or N7 or N8"

# Boundary tests only
pytest tests/ -v -k "B1 or B2 or B3 or B4 or B5 or B6"

# Fault tests only
pytest tests/ -v -k "F1 or F2 or F3 or F4 or F5 or F6 or F7 or F8"

# Cross-skill tests only
pytest tests/ -v -k "C1 or C2"
```

### Lint & Type Check

```bash
# Pre-commit validation
ruff check tests/
ruff format tests/
mypy tests/
```

---

## 10. Gap Analysis

### Missing Interfaces (Flagged)

| Skill | Gap                                  | Severity |
|-------|--------------------------------------|----------|
| S2    | No max task limit documented         | Medium   |
| S3    | No max options limit enforced        | Medium   |
| S4    | No tool capability registry          | High     |
| S5    | No idempotency guarantee documented  | Medium   |
| S6    | No default policy specified          | High     |
| S7    | No independent verification protocol | High     |

### Recommendations

1. **Create tool capability registry** for S4 task assignment
2. **Document policy defaults** in config schema
3. **Define verification independence rules** explicitly
4. **Add idempotency markers** to execution results

---

## 11. Acceptance Criteria

- [x] Plan totals exactly 192 tests (8 skills × 24 each)
- [x] Identifies existing reusable tests (4 tests in test_orchestrator.py, test_issue_parse.py, test_policy.py)
- [x] Provides non-overlapping implementation slices (8 independent slices)
- [x] Includes precise validation commands for each category
- [x] Derived from actual source code and contracts (no invented interfaces)
- [x] Flags gaps in current specification

---

_End of Test Campaign Design_
