# Reconciliation and Crash Recovery Contract

## Overview

OpsSwarm implements a comprehensive reconciliation and crash recovery system to ensure operational continuity after
unexpected shutdowns or failures. This document describes the reconciliation contract, recovery mechanisms, and
integration points.

## Core Components

### 1. ReconciliationManager (`opsswarm/reconciliation.py`)

The `ReconciliationManager` class provides:

- **Reconciliation Reports**: Analyze evidence logs for a run
- **Run Recovery**: Load and recover non-terminal runs on startup
- **Gap Detection**: Identify missing events in evidence sequences
- **Duplicate Handling**: Track and skip duplicate evidence via idempotency keys

### 2. Evidence Deduplication (`opsswarm/evidence.py`)

The `EvidenceStore` class provides:

- **Idempotency Keys**: SHA256-based keys computed from `event_id + run_id + kind`
- **Duplicate Detection**: Skips appending evidence with duplicate idempotency keys
- **Evidence Logging**: JSONL format with timestamps and metadata

### 3. Checkpoint System (`opsswarm/store.py`)

The `RunStore` class provides:

- **Atomic Writes**: Write to `.tmp` file first, then rename (crash-safe)
- **Checkpoint Save**: Save run state at key points
- **Checkpoint Load**: Resume from saved checkpoint
- **Retry Logic**: Save with exponential backoff on failure

## Recovery Flow

### Startup Recovery

```
1. Orchestrator.__init__() called
2. enable_recovery=True (default)
3. _recover_runs() invoked
4. load_non_terminal_runs() finds runs not in {RESOLVED, FAILED, ABORTED}
5. For each non-terminal run:
   a. Check for checkpoint (has_checkpoint, load_checkpoint)
   b. If checkpoint exists: resume from checkpoint
   c. Else if evidence exists: resume from evidence log
   d. Else: mark as requiring manual intervention
```

### Evidence Replay

When resuming from evidence:

1. Load all evidence records for the run (`evidence.list(run_id)`)
2. Reconstruct state by replaying evidence in timestamp order
3. Resume from the last known checkpoint/state

### Gap Detection

The reconciliation process detects:

- Missing expected evidence kinds (S1.incident, S2.task_graph, etc.)
- Incomplete finding sequences (expected N findings, found M)
- Timestamps gaps or out-of-order events

## Reconciliation Report

The `reconcile(run_id)` method returns:

```python
@dataclass
class ReconciliationReport:
    run_id: str
    total_records: int           # Total evidence records
    unique_idempotency_keys: int # Unique evidence entries
    duplicates_skipped: int      # Duplicates detected and skipped
    evidence_kinds: list[str]    # Types of evidence present
    gaps_detected: list[str]     # Missing expected evidence
    last_evidence_timestamp: datetime | None
    generated_at: datetime
```

## Configuration

### Recovery Options

| Option                 | Default | Description                       |
|------------------------|---------|-----------------------------------|
| `enable_recovery`      | `True`  | Enable crash recovery on startup  |
| `enable_atomic_writes` | `True`  | Use atomic writes for persistence |
| `enable_checkpoints`   | `True`  | Enable checkpoint saving          |

### Config File Example

```yaml
persistence:
     enable_recovery: true
     enable_atomic_writes: true
     enable_checkpoints: true
     data_dir: "runtime-data"
```

## Integration with Orchestrator

The `Orchestrator` class integrates recovery:

```python
class Orchestrator:
    def __init__(self, cfg, github, openclaw, data_dir="runtime-data",
                 enable_recovery: bool = True):
        # ... setup ...
        self.reconciliation = ReconciliationManager(data_dir)

        if enable_recovery:
            self._recover_runs()

    def get_reconciliation_report(self, issue_number: int) -> dict | None:
        """Get reconciliation report for a run."""
        return self.reconciliation.get_recovery_plan(self.runs.get(issue_number))
```

## Duplicate Handling

### Evidence Duplicates

When appending evidence:

1. Compute idempotency key: `SHA256(event_id + run_id + kind)`
2. Load existing keys for the run
3. If key exists: skip (log count as duplicate)
4. If key is new: append to evidence log

### Command Duplicates (ADR-009-5)

Each GitHub comment has a unique ID used as idempotency key:

1. Check if comment ID already in `executed_commands`
2. If executed: skip (already processed)
3. If not executed: process and add to `executed_commands`

## Validation

### Unit Tests

Run unit tests for reconciliation:

```bash
pytest tests/unit/ -v -k "reconciliation or recovery"
```

### Integration Tests

Run integration tests for recovery scenarios:

```bash
pytest tests/integration/ -v
```

### Manual Validation

To generate a reconciliation report:

```python
from opsswarm.reconciliation import ReconciliationManager

manager = ReconciliationManager("runtime-data")
report = manager.reconcile("RUN-GH-123-abc123")
print(f"Total records: {report.total_records}")
print(f"Duplicates: {report.duplicates_skipped}")
print(f"Gaps: {report.gaps_detected}")
```

## Rollback Strategy

If reconciliation causes issues:

1. **Disable Recovery**: Set `enable_recovery=False` in config
2. **Disable Atomic Writes**: Set `enable_atomic_writes=False` (less safe but simpler)
3. **Manual Recovery**: Load runs directly from `runtime-data/runs/*.json`

## Related ADRs

| ADR       | Topic                            |
|-----------|----------------------------------|
| ADR-009-1 | Idempotency Strategy             |
| ADR-009-2 | State Enforcement                |
| ADR-009-3 | Checkpoint Strategy              |
| ADR-009-4 | Evidence Deduplication           |
| ADR-009-5 | Command Determinism (First-Wins) |
