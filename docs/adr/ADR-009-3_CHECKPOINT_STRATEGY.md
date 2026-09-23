# ADR-009-3: Checkpoint Granularity for Crash Recovery

**Status:** Proposed  
**Created:** 2026-09-22  
**Related:** Issue #9, PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md

## Context

The current implementation in `opsswarm/store.py` and `opsswarm/orchestrator.py` saves the full RunRecord at each state
transition:

```python
# orchestrator.py:20-26
async def _set_state(self, run:RunRecord, state:RunState):
    run.transition(state)
    self.store.save(run)
```

This provides basic persistence, but lacks explicit checkpoint/resume semantics. If the process crashes between state
transitions, work since the last save is lost. The evidence store (`evidence.py`) provides an append-only audit log, but
recovery requires replay.

## Policy Decision

**Adopt Option A:** Checkpoint at every state transition.

This is the current implicit behavior, but formalized with explicit checkpoint semantics:

1. **State transition checkpoints** — Full RunRecord saved after each `_set_state()` call
2. **Key workflow checkpoints** — Save before human gates (WAITING_APPROVAL, WAITING_DECISION, WAITING_INPUT)
3. **Recovery action checkpoints** — Save before and after S5 execution attempts

### Source Code Anchors

| Concern              | File                             | Current State               |
|----------------------|----------------------------------|-----------------------------|
| State persistence    | `opsswarm/orchestrator.py:20-26` | Saves at every state change |
| Run persistence      | `opsswarm/store.py:10-11`        | Full JSON serialization     |
| Evidence persistence | `opsswarm/evidence.py:12-17`     | Append-only events          |
| Evidence listing     | `opsswarm/evidence.py:19-22`     | Read evidence by run        |

## Alternatives Considered

| Option | Description                | Rejection Rationale                               |
|--------|----------------------------|---------------------------------------------------|
| A      | Every state transition     | Chosen — balance of granularity and storage       |
| B      | Every S4 finding (coarser) | Loses too much work on crash during investigation |
| C      | Every command (finer)      | Overhead without proportional benefit             |

## Checkpoint Types

### 1. State Transition Checkpoints

Save RunRecord after each successful state transition in `_set_state()`:

- OPEN → TRIAGE
- TRIAGE → INVESTIGATING
- INVESTIGATING → DIAGNOSED
- etc.

### 2. Human Gate Checkpoints

Save before transitioning to:

- `WAITING_APPROVAL`
- `WAITING_DECISION`
- `WAITING_INPUT`

These represent "safe points" where human input can resume the workflow.

### 3. Execution Checkpoints

Save before and after S5 recovery execution:

- Pre-execution checkpoint (for retry after failure)
- Post-execution checkpoint (for verification)

## Implementation Dependencies

1. **Checkpoint annotation** (new in `models.py` or `orchestrator.py`)
   ```python
   class CheckpointType(str, Enum):
       STATE_TRANSITION = "state_transition"
       HUMAN_GATE = "human_gate"
       EXECUTION = "execution"
   ```

2. **Checkpoint event** (`evidence.py`)
   ```python
   def checkpoint(self, run_id: str, checkpoint_type: CheckpointType, payload: dict):
       # Record checkpoint for recovery
   ```

3. **Resume logic** (`orchestrator.py`)
    - Detect last valid checkpoint on startup
    - Provide `/opsswarm resume` that loads from checkpoint
    - Current `/opsswarm resume` is limited (orchestrator.py:157-159)

4. **Recovery API** (`api.py`)
    - Expose `GET /runs/{issue_number}/checkpoint` to retrieve last checkpoint
    - Expose `POST /runs/{issue_number}/resume` to resume from checkpoint

## Compatibility & Migration

- **Backwards compatible:** Checkpointing extends existing save behavior
- **Migration:** No data migration required; checkpoints are new events
- **Rollback:** Disable checkpointing by not calling checkpoint logic; degrades to current behavior

## Security Impact

- **Low risk:** Checkpoints are internal state snapshots
- **Data exposure:** Ensure checkpoint files have appropriate access controls
- **Tampering:** Checkpoint integrity verified through existing evidence audit trail

## Source Drift Mitigation

- ADR links to anchors in `store.py`, `orchestrator.py`, `evidence.py`, `api.py`
- Implementation task T10 (Add checkpoint/resume capability) must verify against these sources
- Any changes to state machine must update checkpoint logic
