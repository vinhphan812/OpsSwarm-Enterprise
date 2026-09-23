# ADR-009-5: Approve vs Abort Determinism

**Status:** Proposed
**Created:** 2026-09-22
**Related:** Issue #9, ADR-012

## Context
The current implementation in `opsswarm/orchestrator.py` processes commands with durability guarantees defined in ADR-012 (Command Outcome Model).

Command status is tracked via `command_outcomes` using the `CommandOutcome` enum (see ADR-012).

### Refined Idempotency (Issue #9/ADR-012)
If a user clicks "approve" multiple times rapidly, or if network retries deliver the same comment multiple times, the same recovery action could execute multiple times. ADR-012 ensures safety through the `CommandOutcome` states.

## Policy Decision

**Adopt Option A/B (Durable State Tracking):** First-wins via idempotency + durable state outcome tracking (ADR-012).

### Behavior

1. **Command idempotency key** — Each command execution uses the GitHub comment ID as an idempotency key
2. **First execution wins** — Once a command with a given ID executes, subsequent executions with the same ID are
   rejected
3. **Deterministic outcome** — The first approve/abort is always the one that takes effect

### Source Code Anchors

| Concern           | File                               | Current State                 |
|-------------------|------------------------------------|-------------------------------|
| Command handling  | `opsswarm/orchestrator.py:121-156` | No idempotency                |
| Approve execution | `opsswarm/orchestrator.py:149-156` | Executes directly             |
| Abort execution   | `opsswarm/orchestrator.py:135-136` | Transitions directly          |
| Run state         | `opsswarm/models.py:137-156`       | `command_outcomes` tracking   |

## Command Execution Order

```
User clicks approve (comment A)  ─┐
User clicks approve (comment B)  ─┼──→ Only A executes; B is idempotent reject
User clicks abort (comment C)    ─┘
```

When the run is in terminal states (RESOLVED, FAILED, ABORTED), no commands are accepted regardless of idempotency.

## Alternatives Considered

| Option | Description                | Rejection Rationale                                |
|--------|----------------------------|----------------------------------------------------|
| A      | First-wins via idempotency | Chosen — deterministic, safe                       |
| B      | Last-wins                  | Non-deterministic; race conditions                 |
| C      | Queue and execute all      | Dangerous; could execute multiple recovery actions |

## Idempotency Key Scope

| Command                  | Idempotency Key | Rejection After Execution                                             |
|--------------------------|-----------------|-----------------------------------------------------------------------|
| `/opsswarm approve <id>` | Comment ID      | If run has transitioned from WAITING_APPROVAL or if execution started |
| `/opsswarm abort`        | Comment ID      | If run is already ABORTED                                             |
| `/opsswarm reject`       | Comment ID      | If decision status is already REJECTED                                |
| `/opsswarm provide`      | Comment ID      | If input already applied                                              |
| `/opsswarm investigate`  | Comment ID      | If task already created                                               |
| `/opsswarm resume`       | Comment ID      | If run already left terminal recovery state                           |

## Implementation Dependencies

1. **Add `command_outcomes` to RunRecord** (`models.py`)

2. **Idempotency check in handle_comment** (`orchestrator.py`)

3. **Extract comment_id from webhook payload** (`api.py`)

4. **Terminal state check** (`orchestrator.py`)

## Compatibility & Migration
- **Backwards compatible:** Adding new fields to RunRecord is non-breaking
- **Migration:** Existing runs have no executed_commands; first command always wins
- **Rollback:** Remove command_outcomes field; reverts to legacy behavior

## Security Impact

- **High importance:** Without this, rapid approve clicks or webhook retries could execute the same production change
  multiple times
- **Integrity:** First-wins ensures deterministic outcomes
- **Audit:** Executed commands are tracked for audit purposes

## Source Drift Mitigation

- ADR links to anchors in `orchestrator.py`, `api.py`, `models.py`
- Implementation must verify idempotency at each command handler
- Any new commands must include idempotency handling
