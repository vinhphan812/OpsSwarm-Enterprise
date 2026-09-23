# ADR-009-4: Evidence Duplicate Handling

**Status:** Proposed  
**Created:** 2026-09-22  
**Related:** Issue #9, PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md

## Context

The current implementation in `opsswarm/evidence.py` appends evidence events to a JSONL file without duplicate
detection:

```python
# evidence.py:12-17
def append(self, run_id: str, kind: str, payload: dict[str, Any]) -> str:
    eid=f"EV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    rec={"id":eid,"timestamp":datetime.now(timezone.utc).isoformat(),"run_id":run_id,"kind":kind,"payload":payload}
    with (self.path/f"{run_id}.jsonl").open("a",encoding="utf-8") as f:
        f.write(json.dumps(rec,ensure_ascii=False,default=str)+"\n")
    return eid
```

If a recovery action is retried or a workflow is resumed after a partial failure, duplicate evidence events could be
recorded. This creates:

- Noise in audit logs
- Confusion in downstream analysis
- Potential duplicate notifications or actions

## Policy Decision

**Adopt Option A:** Skip duplicates, log count.

### Behavior

1. **Evidence signature calculation** — For each evidence event, calculate a stable signature based on:
    - `kind` (event type)
    - `run_id` (run identifier)
    - Core payload fields (excluding timestamps and volatile IDs)

2. **Duplicate detection** — Before appending, check if an event with the same signature exists

3. **Skip and log** — If duplicate, skip appending and log the duplicate count

4. **Audit trail preserved** — Original event remains; duplicates are not added

### Source Code Anchors

| Concern         | File                                            | Current State          |
|-----------------|-------------------------------------------------|------------------------|
| Evidence append | `opsswarm/evidence.py:12-17`                    | No duplicate detection |
| Evidence list   | `opsswarm/evidence.py:19-22                     | Returns all events     |
| Evidence usage  | `opsswarm/orchestrator.py:18,52,68,72,85,99,110 | S1-S7 events           |

## Alternatives Considered

| Option | Description                | Rejection Rationale                               |
|--------|----------------------------|---------------------------------------------------|
| A      | Skip duplicates, log count | Chosen — preserves audit trail, avoids processing |
| B      | Keep first occurrence      | Loses temporal information about retries          |
| C      | Keep last occurrence       | Loses information about initial attempt           |

## Evidence Kinds to Monitor

| Kind             | Source                | Signature Key Fields        |
|------------------|-----------------------|-----------------------------|
| S1.incident      | `orchestrator.py:39`  | issue_number, service       |
| S2.task_graph    | `orchestrator.py:52`  | task IDs, types             |
| S4.finding       | `orchestrator.py:68`  | task_id, finding text       |
| RCA.root_cause   | `orchestrator.py:72`  | proximate_cause, root_cause |
| S3.recovery_plan | `orchestrator.py:85`  | option IDs                  |
| S5.execution     | `orchestrator.py:99`  | option_id, summary          |
| S7.verification  | `orchestrator.py:110` | verified, summary           |
| human.approval   | `orchestrator.py:155` | actor, option               |
| human.input      | `orchestrator.py:138` | actor, text                 |

## Implementation Dependencies

1. **Evidence signature function** (`evidence.py`)
   ```python
   def _signature(kind: str, payload: dict) -> str:
       """Calculate stable signature for duplicate detection."""
       stable = {k: v for k, v in payload.items() 
                 if k not in ('timestamp', 'eid', 'id')}
       return hashlib.sha256(
           f"{kind}:{json.dumps(stable, sort_keys=True)}".encode()
       ).hexdigest()[:16]
   ```

2. **Duplicate index** (`evidence.py`)
    - Maintain in-memory index per run: `seen_signatures: dict[str, set[str]]`
    - Or use file-based index for durability

3. **Modified append method** (`evidence.py`)
   ```python
   def append(self, run_id: str, kind: str, payload: dict) -> tuple[str, bool]:
       sig = _signature(kind, payload)
       if run_id not in self._index:
           self._index[run_id] = set()
       if sig in self._index[run_id]:
           return None, True  # duplicate
       self._index[run_id].add(sig)
       # ... existing append logic
   ```

4. **Logging** — Log duplicate events at DEBUG or INFO level with count

## Compatibility & Migration

- **Backwards compatible:** Skip behavior is non-breaking; duplicates are simply not added
- **Migration:** Existing evidence files are not retroactively deduplicated (by design — audit trail)
- **Rollback:** Remove duplicate detection logic; reverts to current append-only behavior

## Security Impact

- **Low risk:** Duplicate detection is internal logic
- **Audit integrity:** Original evidence preserved; duplicate skipping is transparent
- **Denial of service:** Without deduplication, an attacker could flood evidence with duplicates

## Source Drift Mitigation

- ADR links to anchors in `evidence.py`, `orchestrator.py`
- Implementation task T9 (Implement evidence deduplication) must verify against these sources
- Any new evidence kinds must consider signature stability
