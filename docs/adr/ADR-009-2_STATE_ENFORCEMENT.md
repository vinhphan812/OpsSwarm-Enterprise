# ADR-009-2: State Machine Enforcement Level

**Status:** Proposed  
**Created:** 2026-09-22  
**Related:** Issue #9, PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md

## Context

The current implementation in `opsswarm/orchestrator.py` does not enforce valid state transitions. The
`RunRecord.transition()` method (models.py:154-156) simply updates the state without validation:

```python
def transition(self, new_state: RunState) -> None:
    self.state = new_state
    self.updated_at = utc_now()
```

This allows invalid transitions like TRIAGE → RESOLVED or EXECUTING → WAITING_APPROVAL, which breaks the workflow model
defined in ARCHITECTURE.md.

## Policy Decision

**Adopt Option B initially, transition to Option A:** Implement audit mode first, then migrate to strict enforcement.

### Phase 1: Audit Mode (Recommended for initial implementation)

- Log a warning when an invalid transition is attempted
- Allow the transition (for backward compatibility during rollout)
- Emit evidence event with transition details

### Phase 2: Strict Enforcement (Post-observation)

- Raise `InvalidStateTransition` exception for invalid transitions
- Block invalid transitions entirely
- Transition to this after sufficient audit data confirms transition rules are correct

### Source Code Anchors

| Concern               | File                             | Current State                     |
|-----------------------|----------------------------------|-----------------------------------|
| State transition      | `opsswarm/models.py:154-156`     | No validation                     |
| State setter          | `opsswarm/orchestrator.py:20-26` | Calls `run.transition()` directly |
| State machine diagram | `docs/ARCHITECTURE.md:318-336`   | Defines valid states              |
| Flow rules            | `docs/FLOWS.md`                  | Defines valid transitions         |

## Valid State Transitions

```
OPEN → TRIAGE
TRIAGE → INVESTIGATING
INVESTIGATING → DIAGNOSED
DIAGNOSED → PLANNING
PLANNING → WAITING_APPROVAL | WAITING_DECISION | WAITING_INPUT | EXECUTING | FAILED
WAITING_APPROVAL → EXECUTING | WAITING_DECISION | WAITING_INPUT | FAILED | ABORTED
WAITING_DECISION → WAITING_APPROVAL | WAITING_INPUT | EXECUTING | FAILED | ABORTED
WAITING_INPUT → INVESTIGATING | DIAGNOSED | FAILED | ABORTED
EXECUTING → VERIFYING | WAITING_DECISION | FAILED | ABORTED
VERIFYING → RESOLVED | FAILED
RESOLVED → (terminal)
FAILED → WAITING_APPROVAL | WAITING_DECISION | WAITING_INPUT | INVESTIGATING | ABORTED
ABORTED → (terminal)
```

## Alternatives Considered

| Option | Description                               | Rejection Rationale                                               |
|--------|-------------------------------------------|-------------------------------------------------------------------|
| A      | Strict: raise InvalidStateTransition      | Too restrictive for initial rollout; may break existing workflows |
| B      | Audit mode: log warning, allow transition | Chosen — enables gradual rollout and learning                     |
| C      | Disabled: ignore validation               | Defeats the purpose of state machine                              |

## Implementation Dependencies

1. **Define VALID_TRANSITIONS** (`models.py`)
   ```python
   VALID_TRANSITIONS: dict[RunState, set[RunState]] = {
       RunState.OPEN: {RunState.TRIAGE},
       RunState.TRIAGE: {RunState.INVESTIGATING},
       # ... complete mapping
   }
   ```

2. **Add validation to transition()** (`models.py`)
    - Check against VALID_TRANSITIONS
    - Log warning in audit mode
    - Raise exception in strict mode

3. **Config flag for enforcement level** (`config.py`)
   ```python
   "state_enforcement": "audit" | "strict" | "disabled"
   ```

4. **InvalidStateTransition exception** (`models.py` or new `exceptions.py`)

## Compatibility & Migration

- **Backwards compatible:** Audit mode preserves existing behavior
- **Migration:**
    - Deploy with `state_enforcement: audit`
    - Monitor logs for violations
    - After observation period, switch to `strict`
- **Rollback:** Set `state_enforcement: disabled` to revert to no validation

## Security Impact

- **Low risk:** Audit mode only adds logging
- **Integrity:** Strict mode prevents workflow violations that could bypass gates
- **Audit:** Transition events provide full workflow provenance

## Source Drift Mitigation

- ADR links to anchors in `models.py`, `orchestrator.py`, `ARCHITECTURE.md`, `FLOWS.md`
- Implementation task T8 (Implement VALID_TRANSITIONS) must verify against these sources
- Any changes to RunState enum must update both this ADR and VALID_TRANSITIONS
