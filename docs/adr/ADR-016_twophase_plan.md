# ADR-016: Two-Phase Plan — Plan_Remediation (Immediate) vs Plan_RCA (Deferred)

**Status:** Accepted
**Created:** 2026-09-30
**Updated:** 2026-10-01
**Related:** Issue #43, #44, ADR-009-3, ADR-012

---

## Context

The OpsSwarm run-state machine conflates two operationally distinct phases:

**Phase 1 — Service Restoration (Plan_Remediation)**
- Time-critical, bounded, success/failure determinable in minutes.
- Actors: on-call engineers, SRE tooling, autonomous agents.
- SLA: MTTR (Mean Time To Restoration), typically minutes.
- Exit criteria: customer-facing service health restored (verified by S7).

**Phase 2 — Root Cause Analysis and Postmortem (Plan_RCA)**
- Deferred, iterative, success not binary.
- Actors: incident commander, domain experts, possibly a separate RCA workflow.
- SLA: days; requires external coordination and evidence synthesis.
- Exit criteria: RCAReport produced, corrective-action issues filed.

Previously, `make_recovery_plan` (S3) produced a single plan that included immediate remediation steps. After S7 verification, the run terminated at `RESOLVED`. The `corrective_actions` in `RootCauseArtifact` were filed as GitHub issues, but there was no structured RCA capture or postmortem record attached to the run.

This created two problems:
- **Budget bleed**: Phase 1 and Phase 2 shared a single budget, causing RCA to be silently starved.
- **Postmortem loss**: The `postmortem()` helper in `markdown.py` relied on `RootCauseArtifact.corrective_actions`, but no structured RCA artifact was produced after resolution — the postmortem was just a comment, not a durable record.

---

## Decision

**Adopt a two-phase plan with a dedicated Phase-2 RCA state (`PLAN_RCA`).**

```
INVESTIGATING → DIAGNOSED → PLANNING → EXECUTING → VERIFYING → RESOLVED → PLAN_RCA → PLAN_RCA_RESOLVED
                                                                              ↘ ABORTED
```

**Phase 1 — Plan_Remediation** runs in the existing states (`PLANNING`, `EXECUTING`, `VERIFYING`). The orchestrator calls S3 remediation, S5 execution, S7 verification. On success, the state becomes `RESOLVED`.

**Phase 2 — Plan_RCA** runs in `PLAN_RCA` after `RESOLVED`. The orchestrator calls S3-RCA synthesis to produce an `RCAReport`, then files corrective-action GitHub issues. On success, the state becomes `PLAN_RCA_RESOLVED`.

Both phases have independent budgets. If Phase 2 exhausts its budget, the run terminates in `ABORTED` — the incident itself is already `RESOLVED`.

---

## State Model

### New States

| State | Meaning |
|---|---|
| `PLAN_RCA` | Phase-2 RCA synthesis in progress |
| `PLAN_RCA_RESOLVED` | RCA complete; no further transitions |

### Valid Transitions (models.py)

```python
VALID_TRANSITIONS[RunState.RESOLVED] = {
    RunState.PLAN_RCA,           # kick off Phase 2
    RunState.PLAN_RCA_RESOLVED,  # skip RCA when rca_enabled=false
}
VALID_TRANSITIONS[RunState.PLAN_RCA] = {
    RunState.PLAN_RCA_RESOLVED,  # successful synthesis
    RunState.ABORTED,            # budget exhausted or RCA abandoned
}
VALID_TRANSITIONS[RunState.PLAN_RCA_RESOLVED] = set()  # Terminal
```

### Terminal States

```python
TERMINAL_STATES = {RunState.FAILED, RunState.ABORTED, RunState.PLAN_RCA_RESOLVED}
```

Note: `RESOLVED` is **not** in `TERMINAL_STATES` because `PLAN_RCA` is a valid exit path. A run is only fully terminal when it reaches `PLAN_RCA_RESOLVED`, `FAILED`, or `ABORTED`.

---

## Budget Separation

| Budget | Covers |
|---|---|
| `RunBudget` (Phase 1) | S2 investigation, S3 remediation plan, S5 execution, S7 verification |
| `RCABudget` / wall-clock guard (Phase 2) | S3-RCA synthesis, corrective-action issue creation |

Both are capped independently. Phase-2 budget is controlled by `cfg.get("rca_budget", {})` with `max_wall_clock_seconds` (default: 600 s). Token usage is tracked via the existing `RunBudget.mark_openclaw_call()` call. If Phase 2 exhausts its wall-clock limit, the run transitions to `ABORTED` and records the reason in `run.error`.

---

## RCA Report Model

```python
class RCAReport(BaseModel):
    """Structured RCA and postmortem record (ADR-015/ADR-016)."""
    run_id: str = ""
    issue_number: int = 0
    proximate_cause: str = ""
    root_cause: str = ""
    causal_chain: list[str] = Field(default_factory=list)
    contributing_factors: list[str] = Field(default_factory=list)
    what_went_well: list[str] = Field(default_factory=list)
    what_went_poorly: list[str] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)  # [{timestamp, actor, action}]
    evidence_refs: list[str] = Field(default_factory=list)
    corrective_actions: list[dict] = Field(default_factory=list)  # [{description, priority, owner, ticket_url, status}]
    lessons_learned: str = ""
    confidence: float = 0.0
```

`RunRecord` gains two fields:

```python
rca_report: RCAReport | None = None         # Phase-2 structured output
rca_budget_snapshot: dict | None = None     # {"tokens_used": ..., "wall_clock_seconds": ...}
```

`RCAReport.from_root_cause()` adapts a Phase-1 `RootCauseArtifact` into an `RCAReport` for environments where Phase-2 is skipped.

---

## S3-RCA Prompt

The Phase-2 LLM call uses `rca_plan_prompt()` (`prompts.py`):

```
You are OpsSwarm S3-RCA. Produce a structured postmortem and RCA report.
Return JSON: proximate_cause, root_cause, causal_chain[],
contributing_factors[], what_went_well[], what_went_poorly[],
timeline[{timestamp,actor,action}], evidence_refs[],
corrective_actions[{description,priority,owner}], lessons_learned, confidence.
```

`synthesize_rca()` (`skill_logic.py`) wraps this with `S.synthesize()` and returns an `RCAReport`.

---

## Orchestrator Changes (orchestrator.py)

After `_verify()` sets `RunState.RESOLVED`:

```python
if self.cfg.get("rca_enabled", True):
    await self._plan_rca(run)
```

`_plan_rca(run)`:
1. Transitions to `PLAN_RCA`, sets `phase:rca` GitHub label.
2. Checks RCA wall-clock budget; aborts if exhausted.
3. Calls `S.synthesize_rca(...)` → populates `run.rca_report`.
4. Saves `run.rca_budget_snapshot`.
5. Transitions to `PLAN_RCA_RESOLVED`.
6. For each `corrective_action` in `run.rca_report`, creates a GitHub issue tagged `opsswarm:corrective-action` with priority, owner, and parent incident reference.

---

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `rca_enabled` | `true` | Enable/disable Phase-2 RCA entirely |
| `rca_budget.max_wall_clock_seconds` | `600` | Phase-2 wall-clock cap |
| `create_corrective_issues` | `true` | File corrective-action issues in GitHub |
| `rca_label` | `"phase:rca"` | GitHub label applied in `PLAN_RCA` |

When `rca_enabled=false`, the orchestrator transitions directly from `RESOLVED` to `PLAN_RCA_RESOLVED`, skipping Phase 2.

---

## Compatibility & Migration

- `rca_enabled: false` in config disables Phase 2 — existing runs are unaffected.
- `RCAReport` field on `RunRecord` is optional — existing serialized records load without error.
- `PLAN_RCA_RESOLVED` is treated as terminal in `handle_comment()` (guards against processing commands on closed incidents).
- `from_root_cause()` adapter provides backward compatibility for integrations that consume Phase-1 artifacts.

---

## Source Code Anchors

| Concern | File | Line |
|---|---|---|
| New states | `models.py` | `RunState.PLAN_RCA`, `PLAN_RCA_RESOLVED` |
| Valid transitions | `models.py` | `VALID_TRANSITIONS[...]` entries |
| Terminal states | `models.py` | `TERMINAL_STATES` |
| RCA report model | `models.py` | `RCAReport` class |
| RunRecord fields | `models.py` | `rca_report`, `rca_budget_snapshot` |
| S3-RCA prompt | `prompts.py` | `rca_plan_prompt()` |
| `synthesize_rca` | `skill_logic.py` | `async def synthesize_rca()` |
| `_plan_rca` | `orchestrator.py` | `async def _plan_rca()` |
| RCA gate | `orchestrator.py` | `if self.cfg.get("rca_enabled", True)` |
| RCA label | `orchestrator.py` | `_set_labels` → `PLAN_RCA` branch |
| Terminal-state guard | `orchestrator.py` | `handle_comment()` → `TERMINAL_STATES` |

---

## Consequences

**Positive:**
- Phase 1 and Phase 2 have independent budgets; RCA is no longer starved by remediation.
- `RCAReport` is a durable, structured artifact attached to the `RunRecord`.
- Corrective-action issues are created from structured data, not ad-hoc comments.
- Phase 2 can be disabled via config for environments that handle RCA externally.

**Negative:**
- `RESOLVED` is no longer terminal — callers that check `state in TERMINAL_STATES` must account for Phase 2.
- Added complexity in the orchestrator's `_verify()` path.

**Mitigation:** `PLAN_RCA_RESOLVED` is a true terminal state. Any code that only cares about the incident being resolved can check `state == RunState.RESOLVED`; any code that cares about the full run completing should check `state in TERMINAL_STATES`.
