# ADR-015: Two-Phase Plan: Immediate Remediation (Plan_Remediation) vs. Deferred RCA/Postmortem (Plan_RCA)

**Status:** Proposed
**Created:** 2026-09-30
**Related:** Issue #43, ADR-012, ADR-009-3

## Context

The OpsSwarm run-state machine conflates two operationally distinct phases:

1. **Service restoration** — time-critical, bounded, success/failure determinable in minutes.
   - Actors: on-call engineers, SRE tooling, potentially autonomous agents.
   - SLA: MTTR (Mean Time To Restoration), typically minutes.
   - Exit criteria: customer-facing service health restored (verified by S7).

2. **Root Cause Analysis and postmortem** — deferred, iterative, success not binary.
   - Actors: incident commander, domain experts, possibly a separate RCA workflow.
   - SLA: MTTR post-incident (days), often requires external coordination.
   - Exit criteria: RCA document produced, corrective actions filed.

Currently, `make_recovery_plan` (S3) produces a single plan that includes immediate remediation. After verification (S7), the run terminates at `RESOLVED`. The `corrective_actions` in `RootCauseArtifact` are filed as GitHub issues, but there is no structured RCA capture, causal analysis, or postmortem template attached to the run record.

This creates two problems:
- **Budget bleed**: The same per-run budget (token, wall-clock, corrective-actions) is shared between restoration and RCA, causing RCA to be silently starved.
- **Postmortem loss**: The `postmortem()` markdown helper in `markdown.py` pulls from `RootCauseArtifact.corrective_actions`, but no structured RCA artifact is produced after resolution — the postmortem is just a comment, not a durable record.

## Evaluation of Options

|| Option | Description | Complexity | Risk |
|| ------ | ----------- | ---------- | ---- |
|| A | Keep as-is; RCA is implicit in corrective actions | Low | RCA starved by shared budget; no structured postmortem record |
|| B | Add separate `Plan_RCA` state with a second LLM call after VERIFICATION | Medium | Clear phase split; RCA has dedicated budget and state |
|| C | Two separate RunRecords (parent incident + child RCA) | High | Full isolation; complex cross-run state management |

## Decision

**Adopt Option B: Two-phase plan with dedicated Plan_RCA state.**

### Phase Architecture

```
RESOLVED
  │
  ▼
PLAN_RCA          ← new state: orchestrator calls S3-RCA prompt
  │
  ▼
PLAN_RCA_RESOLVED ← new terminal state: RCA complete
```

- **Plan_Remediation** (existing S3) runs in `PLANNING` state, produces `RecoveryPlan` options, executes one, verifies via S7.
- **Plan_RCA** (new S3-RCA) runs in `PLAN_RCA` state after `RESOLVED`, produces `RCAReport`, files corrective-action issues, terminates in `PLAN_RCA_RESOLVED`.
- Both phases use the same `RecoveryPlan` model for Phase 1; Phase 2 produces a new `RCAReport` model.
- `PLAN_RCA` and `PLAN_RCA_RESOLVED` are *sub-states* of `RESOLVED` — they share the terminal nature of `RESOLVED` from the perspective of the incident run, but represent a separate budget envelope.

### Budget Separation

Two independent budget envelopes:

| Budget | Covers |
|--------|--------|
| Phase 1 (existing `RunBudget`) | S2 investigation, S3 remediation plan, S5 execution, S7 verification |
| Phase 2 (`RCABudget`) | S3-RCA synthesis, corrective-action issue creation |

Both are capped independently. If Phase 2 exhausts its budget, the run terminates in `PLAN_RCA` (RCA incomplete) — the incident is still `RESOLVED`.

### State Transition Additions

New in `models.py`:

```python
class RunState(str, Enum):
    ...
    PLAN_RCA = "PLAN_RCA"           # Deferred RCA in progress
    PLAN_RCA_RESOLVED = "PLAN_RCA_RESOLVED"  # RCA complete

VALID_TRANSITIONS[RunState.RESOLVED] = {
    RunState.PLAN_RCA,
    RunState.PLAN_RCA_RESOLVED,  # skip RCA if disabled
}
VALID_TRANSITIONS[RunState.PLAN_RCA] = {
    RunState.PLAN_RCA_RESOLVED,
    RunState.ABORTED,             # RCA abandoned
}
VALID_TRANSITIONS[RunState.PLAN_RCA_RESOLVED] = set()  # Terminal
```

### RCA Report Model

```python
class RCAReport(BaseModel):
    """Structured RCA and postmortem record (ADR-015)."""
    run_id: str
    issue_number: int
    proximate_cause: str
    root_cause: str
    causal_chain: list[str]
    contributing_factors: list[str]
    what_went_well: list[str]
    what_went poorly: list[str]
    timeline: list[TimelineEvent]
    evidence_refs: list[str]
    corrective_actions: list[CorrectiveAction]
    lessons_learned: str
    confidence: float

class TimelineEvent(BaseModel):
    timestamp: str
    actor: str
    action: str

class CorrectiveAction(BaseModel):
    description: str
    priority: Literal["critical", "high", "medium", "low"]
    owner: str | None
    ticket_url: str | None
    status: Literal["proposed", "filed"] = "proposed"
```

### RunRecord Additions

```python
class RunRecord(BaseModel):
    ...
    rca_report: RCAReport | None = None
    rca_budget_snapshot: dict | None = None
```

### New Prompt (S3-RCA)

```python
def rca_plan_prompt(incident, root, findings, human_inputs) -> str:
    return f"""You are OpsSwarm S3-RCA. Produce a structured postmortem and RCA report.
Return JSON: proximate_cause, root_cause, causal_chain[], contributing_factors[],
what_went_well[], what_went_poorly[], timeline[{{timestamp,actor,action}}],
evidence_refs[], corrective_actions[{{description,priority,owner}}],
lessons_learned, confidence.
{JSON_ONLY}
Incident: ...
Root cause: ...
Findings: ...
"""
```

### GitHub Label Addition

- `PLAN_RCA` → label `"phase:rca"` (configurable, via `cfg.get("labels.lifecycle")`)

## Orchestrator Changes

1. `orchestrator.py`: after `_verify()` sets `RunState.RESOLVED`, call `_plan_rca(run)` if `cfg.get("rca_enabled", True)`.
2. `_plan_rca(run)`:
   - Transitions to `PLAN_RCA`.
   - Synthesizes `RCAReport` via `S.synthesize_rca()`.
   - Files corrective-action GitHub issues (each with `opsswarm:corrective-action`).
   - Transitions to `PLAN_RCA_RESOLVED` or `ABORTED` on failure.
3. `RCABudget` class: mirrors `RunBudget` but with a separate token/wall-clock cap.

## Security Impact

- Low: RCA phase is read-only synthesis (Phase 1 execution is already complete).
- Corrective-action issues are filed in the same org; no new access vectors.

## Compatibility & Migration

- `rca_enabled: false` in config disables the phase entirely — existing runs remain unaffected.
- `RCAReport` field on `RunRecord` is optional — existing serialized records load without error.
- `PLAN_RCA_RESOLVED` is treated as terminal for terminal-state checks in `handle_comment()`.

## Source Code Anchors

|| Concern | File | Line |
|---------|-------|------|
| New states | `models.py` | `RunState` enum |
| New transitions | `models.py` | `VALID_TRANSITIONS` |
| RCA report model | `models.py` | `RCAReport`, `TimelineEvent`, `CorrectiveAction` |
| RunRecord field | `models.py` | `RunRecord.rca_report` |
| S3-RCA prompt | `prompts.py` | `rca_plan_prompt()` |
| `synthesize_rca` | `skill_logic.py` | new function |
| `_plan_rca` | `orchestrator.py` | new method |
| `_verify()` extension | `orchestrator.py` | after `RESOLVED` transition |
| `terminal-state` check | `orchestrator.py` | `handle_comment()` |
| `resolved()` template | `markdown.py` | unchanged |
| `postmortem()` template | `markdown.py` | enhanced to use `rca_report` |
