# TRIAGE #9: Design persistence, idempotency, concurrency and recovery

**Issue:** https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/9
**Status:** Architecture Design
**Author:** dev-architect
**Date:** 2026-09-22

---

## 1. Current State Flow Trace

### 1.1 Incident Lifecycle (As-Is)

```
[GitHub Webhook: issue_opened] → start_issue()
    ├── Load/Create RunRecord (JSON file)
    ├── Parse IncidentContext from GitHub issue
    ├── Transition to TRIAGE
    ├── Invoke S2 → build_tasks()
    └── Transition to INVESTIGATING

[Investigation Phase]
    ├── Execute tasks in dependency order (waves)
    ├── Save findings to RunRecord + EvidenceStore
    └── Synthesize RCA → transition to DIAGNOSED

[Decision Phase]
    ├── Policy classify_plan() → AUTO/APPROVAL/DECISION/INPUT
    ├── AUTO: execute option directly
    └── WAITING_* states: await human input via GitHub comment

[Execution Phase]
    ├── Execute remediation via S5
    ├── Handle ambiguous outcomes → WAITING_DECISION
    └── Transition to VERIFYING

[Verification Phase]
    ├── S7 verify_recovery()
    ├── SUCCESS → RESOLVED → close issue
    └── FAILURE → FAILED
```

### 1.2 Current Persistence Model

| Component | Storage                              | Mechanism                       |
|-----------|--------------------------------------|---------------------------------|
| RunRecord | `{data_dir}/runs/{run_id}.json`      | Full JSON rewrite on every save |
| Evidence  | `{data_dir}/evidence/{run_id}.jsonl` | Append-only JSONL               |
| Config    | `config/production.yaml`             | Static YAML                     |

### 1.3 Current State Machine (models.py:12-25)

```
OPEN → TRIAGE → INVESTIGATING → DIAGNOSED → PLANNING → EXECUTING → VERIFYING → RESOLVED
  |                    |              |            |           |           |
  +--------------------+--------------+------------+-----------+-----------+
  |                    |              |            |           |
  +-- WAITING_APPROVAL +-- WAITING_DECISION +-- WAITING_INPUT
  |
  +-- FAILED
  +-- ABORTED
```

---

## 2. Gap Analysis

### 2.1 Critical Gaps (Require ADR Decision)

| Gap                            | Severity | Location                  | Evidence                                                    |
|--------------------------------|----------|---------------------------|-------------------------------------------------------------|
| No webhook idempotency         | CRITICAL | `api.py:35-48`            | No deduplication of GitHub delivery IDs                     |
| No command idempotency         | HIGH     | `orchestrator.py:121-158` | Duplicate `/opsswarm approve` could execute twice           |
| No terminal state monotonicity | HIGH     | `models.py:154-156`       | `transition()` allows any state → any state                 |
| No transaction semantics       | HIGH     | `orchestrator.py`         | Multi-step ops (e.g., execute → verify) can fail mid-stream |
| No evidence reconciliation     | MEDIUM   | `evidence.py:12-17`       | Duplicate appends on retried operations                     |

### 2.2 Medium Gaps

| Gap                           | Severity | Location                | Evidence                                          |
|-------------------------------|----------|-------------------------|---------------------------------------------------|
| No crash recovery contract    | MEDIUM   | `store.py:10-11`        | JSON rewrite can corrupt on crash                 |
| No evidence deduplication     | MEDIUM   | `evidence.py`           | Same event logged multiple times on retry         |
| No command ordering guarantee | MEDIUM   | `orchestrator.py:121`   | Comments processed in GitHub API order (unstable) |
| No checkpoint/resume          | MEDIUM   | `orchestrator.py:43-79` | Restart requires full re-investigation            |

### 2.3 Low Gaps

| Gap                         | Severity | Location                  | Evidence                                         |
|-----------------------------|----------|---------------------------|--------------------------------------------------|
| No recovery plan versioning | LOW      | `models.py:102-108`       | Plan overwritten on modification                 |
| No decision audit trail     | LOW      | `orchestrator.py:147-156` | Approval stored but not cryptographically signed |

---

## 3. Proposed Persistence and Identity Model

### 3.1 Idempotency Keys

**Webhooks:**

- Use GitHub's `X-GitHub-Delivery` header as idempotency key
- Store `{delivery_id}` in `RunRecord.webhook_ids: list[str]` to detect duplicates

**Commands:**

- Use comment ID (`comment["id"]`) as idempotency key
- Store `processed_comment_ids: set[int]` in `RunRecord`
- Reject processing if comment ID already in set

### 3.2 Evidence Identity Model

```
EvidenceRecord {
  id: str                    # EV-YYYYMMDDHHMMSSffffff
  event_id: str              # GitHub delivery ID or comment ID
  idempotency_key: str       # SHA256(event_id + run_id + kind)
  run_id: str
  kind: str                  # S1.incident, S4.finding, etc.
  payload: dict
  timestamp: datetime
  checksum: str              # SHA256(payload)
}
```

**Deduplication:** Before appending, compute idempotency_key, check if exists in evidence log, skip if found.

### 3.3 RunRecord Schema Extension

```python
class RunRecord(BaseModel):
    # ... existing fields ...

    # Idempotency
    webhook_ids: list[str] = Field(default_factory=list)
    processed_comment_ids: list[int] = Field(default_factory=list)
    idempotency_keys: list[str] = Field(default_factory=list)

    # Recovery
    checkpoint_state: str | None = None  # Serialized checkpoint
    last_checkpoint_at: datetime | None = None

    # Concurrency
    command_sequence: list[CommandRecord] = Field(default_factory=list)
```

---

## 4. State Machine & Terminal Monotonicity Rules

### 4.1 Terminal States (No Transitions Out)

- `RESOLVED` — Incident closed, verified, and postmortem posted
- `ABORTED` — Human explicitly aborted
- `FAILED` — Unrecoverable error (verification failed, no valid options, etc.)

### 4.2 Monotonicity Rules

```
VALID_TRANSITIONS = {
    None: {OPEN, TRIAGE},           # Start
    OPEN: {TRIAGE},
    TRIAGE: {INVESTIGATING, FAILED, ABORTED},
    INVESTIGATING: {DIAGNOSED, WAITING_INPUT, FAILED, ABORTED},
    DIAGNOSED: {PLANNING, WAITING_INPUT, FAILED, ABORTED},
    PLANNING: {EXECUTING, WAITING_APPROVAL, WAITING_DECISION, WAITING_INPUT, FAILED, ABORTED},
    EXECUTING: {VERIFYING, WAITING_DECISION, FAILED, ABORTED},
    VERIFYING: {RESOLVED, FAILED, ABORTED},
    WAITING_APPROVAL: {PLANNING, EXECUTING, ABORTED},  # After approve/reject
    WAITING_DECISION: {PLANNING, EXECUTING, INVESTIGATING, ABORTED},
    WAITING_INPUT: {DIAGNOSED, INVESTIGATING, ABORTED},
}
```

**Rule:** Only transitions in `VALID_TRANSITIONS[current_state]` are permitted. Any invalid transition raises
`InvalidStateTransition`.

### 4.3 Terminal Enforcement

```python
def transition(self, new_state: RunState) -> None:
    if self.state in {RunState.RESOLVED, RunState.ABORTED, RunState.FAILED}:
        raise InvalidStateTransition(f"Cannot transition from terminal state {self.state}")
    if new_state not in VALID_TRANSITIONS.get(self.state, {new_state}):
        raise InvalidStateTransition(f"Invalid transition {self.state} -> {new_state}")
    self.state = new_state
    self.updated_at = utc_now()
```

---

## 5. Deterministic Approve vs Abort Semantics

### 5.1 Command Processing Order

1. **De-duplicate** by comment ID before processing
2. **Validate authority** (permission check)
3. **Apply state transition**
4. **Record command** in `command_sequence`
5. **Execute side effects**

### 5.2 Approve Semantics

```
/opsswarm approve <option_id>

Preconditions:
- Run state ∈ {WAITING_APPROVAL, WAITING_DECISION}
- Option exists in recovery_plan.options
- Policy allows option (action != "DENY")

Postconditions:
- decision.status = "ANSWERED"
- Execute option via _execute_option()
- If execution succeeds → VERIFYING
- If execution ambiguous → WAITING_DECISION
- If execution fails → FAILED
```

### 5.3 Abort Semantics

```
/opsswarm abort

Preconditions:
- Run state ≠ terminal (RESOLVED, ABORTED, FAILED)
- Actor permission ≥ min_permission_for_abort

Postconditions:
- state = ABORTED
- error = f"Aborted by @{actor}"
- No further processing
- Evidence preserved for audit
```

### 5.4 Idempotent Command Processing

```python
async def handle_comment(self, number, actor, body, permission, command, comment_id):
    run = self.runs.get(number)
    if not run:
        return

    # Idempotency check
    if comment_id in run.processed_comment_ids:
        return  # Already processed

    # ... process command ...

    # Record after successful processing
    run.processed_comment_ids.append(comment_id)
    run.command_sequence.append(CommandRecord(
        comment_id=comment_id,
        actor=actor,
        command=command.name,
        argument=command.argument,
        timestamp=utc_now()
    ))
    await self._save(run, "command.processed", {...})
```

---

## 6. Recovery and Evidence-Reconciliation Contracts

### 6.1 Crash Recovery Contract

**On Restart:**

1. Load all `RunRecord` from `{data_dir}/runs/`
2. For each non-terminal run:
    - Load evidence log from `{data_dir}/evidence/{run_id}.jsonl`
    - Replay evidence to reconstruct state
    - Resume from last checkpoint

**Checkpoint Strategy:**

- Checkpoint after each state transition
- Checkpoint after each command processed
- Checkpoint after each S4 finding (expensive to recompute)

### 6.2 Evidence Reconciliation

**Gap Detection:**

- Compare evidence log sequence with expected sequence
- Missing events → re-fetch from GitHub API if possible
- Duplicate events → deduplicate by idempotency_key

**Reconciliation Algorithm:**

```python
def reconcile(run_id: str) -> ReconciliationReport:
    evidence = evidence_store.list(run_id)
    seen_keys = set()
    duplicates = []
    for e in evidence:
        key = e.get("idempotency_key")
        if key in seen_keys:
            duplicates.append(e)
        else:
            seen_keys.add(key)
    return ReconciliationReport(
        total=len(evidence),
        unique=len(seen_keys),
        duplicates=duplicates
    )
```

### 6.3 Ambiguous Side-Effect Reconciliation

**Current Behavior (Ambiguous Execution):**

- `ExecutionResult.ambiguous = True` → pause in `WAITING_DECISION`
- Require human to investigate externally and confirm

**Proposed Enhancement:**

- Store execution attempt with idempotency key
- On resume, check if effect was applied (external state query)
- Deterministic retry only if idempotency confirmed

---

## 7. Compatibility, Migration, and Rollback Strategy

### 7.1 Backward Compatibility

- New fields in `RunRecord` have defaults (no breaking changes)
- Evidence format adds optional fields (backward compatible)
- State machine accepts legacy transitions (graceful degradation)

### 7.2 Migration Plan

**Phase 1: Add Idempotency Fields**

- Deploy code with new fields (optional)
- No data migration needed

**Phase 2: Enable Idempotency Checks**

- Deploy webhook/command deduplication
- Existing runs continue normally

**Phase 3: Enable State Machine Enforcement**

- Deploy transition validation
- Existing invalid transitions logged but allowed (audit mode)
- After observation period → strict mode

### 7.3 Rollback Strategy

| Version                  | Rollback To         |
|--------------------------|---------------------|
| v2.2 (current)           | v2.1                |
| v2.2 + idempotency       | v2.2 (disable flag) |
| v2.2 + state enforcement | v2.2 + idempotency  |

**Rollback Flag:**

```yaml
persistence:
     enable_idempotency: false
     enable_state_enforcement: false
     enable_checkpoints: false
```

---

## 8. Security and Authorization Impact

### 8.1 New Attack Surfaces

| Surface                 | Risk   | Mitigation                                       |
|-------------------------|--------|--------------------------------------------------|
| Idempotency key forgery | LOW    | Keys are GitHub-managed IDs, not user-controlled |
| State machine bypass    | MEDIUM | Strict validation in `transition()`              |
| Evidence tampering      | MEDIUM | Append-only + optional checksum                  |

### 8.2 Authorization Changes

- Command processing now requires unique comment ID (already GitHub-provided)
- No new permission levels needed
- Authority checks remain in `handle_comment()` per existing policy

### 8.3 Audit Requirements

- All commands recorded with actor, timestamp, comment_id
- Evidence log append-only (no delete/modify)
- State transitions logged with previous/next state

---

## 9. Implementation Decomposition

### 9.1 Child Tasks (ADR-Required)

| Task | Description                             | ADR Dependencies |
|------|-----------------------------------------|------------------|
| T1   | Implement idempotency keys for webhooks | This triage      |
| T2   | Implement command deduplication         | This triage      |
| T3   | Add state machine validation            | This triage      |
| T4   | Add evidence reconciliation             | This triage      |

### 9.2 Implementation Tasks (Post-ADR)

| Task | Description                                        | Parent |
|------|----------------------------------------------------|--------|
| T5   | Add idempotency fields to RunRecord                | T1     |
| T6   | Implement webhook deduplication in api.py          | T1     |
| T7   | Implement command deduplication in orchestrator.py | T2     |
| T8   | Implement VALID_TRANSITIONS and enforce            | T3     |
| T9   | Implement evidence deduplication                   | T4     |
| T10  | Add checkpoint/resume capability                   | T4     |
| T11  | Write integration tests                            | All    |

### 9.3 Test Plan

| Test                        | Scenario                       | Expected                     |
|-----------------------------|--------------------------------|------------------------------|
| test_webhook_idempotency    | Same delivery sent 3x          | Process once                 |
| test_command_idempotency    | Same approve comment sent 2x   | Execute once                 |
| test_invalid_transition     | TRIAGE → RESOLVED              | Raise InvalidStateTransition |
| test_evidence_deduplication | Retry after partial failure    | No duplicate evidence        |
| test_crash_recovery         | Kill during execution, restart | Resume from checkpoint       |

---

## 10. ADR-Required Decisions

The following policies require explicit Architecture Decision Records:

### ADR-009-1: Idempotency Strategy

**Question:** How should webhook and command idempotency be implemented?

**Options:**

- A. Use GitHub delivery/comment IDs as idempotency keys (per this design)
- B. Use application-generated UUIDs
- C. Use content hashing

**Recommendation:** Option A — GitHub-managed IDs are already unique and tamper-resistant.

### ADR-009-2: State Machine Enforcement Level

**Question:** Should invalid state transitions raise errors or be allowed with warning?

**Options:**

- A. Strict: raise InvalidStateTransition (per this design)
- B. Audit mode: log warning, allow transition
- C. Disabled: ignore validation

**Recommendation:** Option B initially, transition to Option A after observation.

### ADR-009-3: Checkpoint Strategy

**Question:** How granular should crash recovery checkpoints be?

**Options:**

- A. Every state transition (per this design)
- B. Every S4 finding (coarser)
- C. Every command (finer)

**Recommendation:** Option A — balance between recovery granularity and storage overhead.

### ADR-009-4: Evidence Reconciliation

**Question:** How should duplicate evidence be handled?

**Options:**

- A. Skip duplicates, log count (per this design)
- B. Keep first occurrence
- C. Keep last occurrence

**Recommendation:** Option A — preserves full audit trail while avoiding processing.

### ADR-009-5: Approve vs Abort Determinism

**Question:** Should multiple rapid approve commands all execute or only the first?

**Options:**

- A. First-wins via idempotency (per this design)
- B. Last-wins (non-deterministic)
- C. Queue and execute all (dangerous)

**Recommendation:** Option A — deterministic, safe.

---

## 11. Summary

This triage identifies critical gaps in persistence, idempotency, concurrency, and recovery:

1. **No idempotency** — webhooks and commands can be processed multiple times
2. **No state machine enforcement** — any state can transition to any state
3. **No evidence reconciliation** — duplicate entries possible
4. **No explicit recovery contract** — crash recovery is implicit/imperfect

The proposed design adds:

- Idempotency keys from GitHub (delivery ID, comment ID)
- State machine with VALID_TRANSITIONS rules
- Evidence deduplication via idempotency_key
- Checkpoint/resume capability
- Deterministic command processing (first-wins)

**This design is sufficient for Tier 3 implementation decision.**
