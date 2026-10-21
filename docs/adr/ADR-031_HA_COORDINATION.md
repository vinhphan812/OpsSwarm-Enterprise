# ADR-030: High-Availability Multi-Process Coordination

**Status:** Proposed  
**Created:** 2026-10-21  
**Related:** Issue #70

---

## Context

The current implementation in `opsswarm/store.py`, `opsswarm/evidence.py`, `opsswarm/orchestrator.py`, and `opsswarm/reconciliation.py` is designed for single-process single-node operation:

- **RunStore** persists `RunRecord` JSON files to `runtime-data/runs/` using atomic writes (tmp + rename, fsync).
- **EvidenceStore** appends JSONL records to `runtime-data/evidence/{run_id}.jsonl` using per-run advisory file locks (`fcntl` / `msvcrt.locking`) that are scoped to the **host OS** — they block concurrent processes on the same machine but provide no protection across machines.
- **RunRecord** tracks command outcomes via `command_outcomes` and webhook idempotency via `idempotency_keys`.
- **ReconciliationManager** loads non-terminal runs on startup and recovers from checkpoints or evidence replay.
- The FastAPI app (`api.py`) is a single uvicorn worker: the `engine = Orchestrator(...)` object is a process-level singleton.

If the process crashes or the host goes down, the incident investigation stops. If a second process is started alongside the first, both will process the same webhook independently — racing to write the same JSON files and appending duplicate evidence records — because:

1. The per-run file locks (`EvidenceStore._process_lock`) are advisory and only effective within one machine.
2. The `Orchestrator.runs` dict is an in-memory `dict[int, RunRecord]` that is never synchronized across processes.
3. There is no mechanism to serialize webhook ingestion or run-state transitions across processes.

Production deployments increasingly require multi-host HA — either active/active (multiple processes serving webhooks simultaneously) or active/passive (a warm standby that takes over on primary failure). This ADR defines the coordination layer that makes that safe.

## Policy Decision

**Adopt a PostgreSQL-backed coordination layer as the single source of truth for cross-process state.**

The rationale for PostgreSQL over alternatives:

| Property | PostgreSQL | Redis | In-memory (current) |
|---|---|---|---|
| Cross-host coordination | ✅ via TCP | ✅ | ❌ |
| Durable writes | ✅ (WAL) | optional (AOF/RDB) | ❌ |
| Existing infrastructure | Often already present | Requires separate deployment | N/A |
| Transactional CAS | ✅ (`SELECT FOR UPDATE`) | Lua + WATCH | ❌ |
| Schema migration tooling | ✅ (Alembic) | N/A | N/A |
| No new infrastructure | ✅ (existing Postgres) | ❌ | N/A |
| Codebase evidence | Not present — this ADR introduces it | Not present — excluded from scope | Current state |

**Scope exclusion (no Redis):** No part of this ADR references BullMQ, Redis, or any message-queue infrastructure unless evidence of such usage appears in the codebase first.

**Bounded HA guarantee:** OpsSwarm HA is bounded to **active/passive with manual failover** for the initial implementation phase. Active/active (multiple processes serving webhooks simultaneously) is explicitly deferred to a future ADR.

---

## Single-Node vs HA Supported Guarantees

| Scenario | Single-node (current) | HA — active/passive (this ADR) |
|---|---|---|
| Process crash + restart | Recovered via checkpoints (ADR-009-3) | Same; standby takes over with same persisted state |
| Host power failure | Lost in-flight work | Standby restarts from last durable write |
| Webhook duplicate delivery | Deduplicated via `idempotency_keys` (ADR-009-1) | Same (idempotency_keys stored in Postgres) |
| Command idempotency | First-wins via `command_outcomes` (ADR-012) | Same (durable Postgres row) |
| Two processes racing | **Data corruption / duplicate evidence** | Serialized via `SELECT FOR UPDATE` |
| Evidence integrity | SHA-256 rolling hash chain (ADR-009-4) | Same chain, stored in Postgres |
| Rate limiting (monitoring ingress) | In-memory `SimpleRateLimiter` (ADR-014-2) | Shared Postgres rate-limit table |
| Readiness probe | Always returns 200 (no coordination check) | Fails-closed until Postgres + leadership verified |

---

## PostgreSQL Schema

### Tables

```sql
-- HA coordination and state table
CREATE TABLE runs (
    run_id         TEXT        NOT NULL PRIMARY KEY,
    issue_number   INTEGER     NOT NULL,
    state          TEXT        NOT NULL,
    run_data       JSONB       NOT NULL,        -- full RunRecord.model_dump()
    revision       INTEGER     NOT NULL DEFAULT 1,
    idempotency_keys TEXT[]    NOT NULL DEFAULT '{}',
    command_outcomes JSONB     NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-issue index (fast lookup for start_issue)
CREATE INDEX idx_runs_issue ON runs (issue_number);

-- Run leadership lease
CREATE TABLE run_leases (
    run_id      TEXT        NOT NULL PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    owner_id    TEXT        NOT NULL,           -- process-unique instance ID
    expires_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT  no_expired_leases CHECK (expires_at > NOW())
);

-- Evidence log (replaces JSONL files)
CREATE TABLE evidence (
    id              TEXT        NOT NULL PRIMARY KEY,
    run_id          TEXT        NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind            TEXT        NOT NULL,
    payload         JSONB       NOT NULL,
    signature       TEXT        NOT NULL,       -- SHA-256 rolling hash (ADR-009-4)
    idempotency_key TEXT,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, id)
);

CREATE INDEX idx_evidence_run ON evidence (run_id);
CREATE INDEX idx_evidence_sig ON evidence (run_id, signature);

-- Anti-replay / rate-limit state (shared across processes)
CREATE TABLE rate_limit_buckets (
    key             TEXT        NOT NULL PRIMARY KEY,
    hits            INTEGER     NOT NULL DEFAULT 0,
    window_start    TIMESTAMPTZ NOT NULL,
    window_seconds  INTEGER     NOT NULL DEFAULT 3600,
    UNIQUE(key, window_start)
);

-- Checkpoints (replaces .checkpoint files)
CREATE TABLE checkpoints (
    run_id          TEXT        NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    checkpoint_type  TEXT        NOT NULL,
    payload          JSONB       NOT NULL,
    sequence        INTEGER     NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, sequence)
);

-- Idempotency key deduplication
CREATE TABLE seen_delivery_keys (
    delivery_id  TEXT        NOT NULL PRIMARY KEY,
    run_id      TEXT        NOT NULL,
    seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Revision-based CAS (Compare-and-Swap)

Every mutating operation on the `runs` table uses optimistic locking:

```python
-- Optimistic CAS: UPDATE only if revision matches
UPDATE runs
SET    run_data = $new_data,
       revision = revision + 1,
       updated_at = NOW(),
       idempotency_keys = $idempotency_keys,
       command_outcomes = $command_outcomes
WHERE  run_id = $run_id
  AND  revision = $expected_revision;
-- If rowcount == 0: StaleDataError → retry or propagate
```

`SELECT FOR UPDATE` is used for leadership transfers to prevent two processes from simultaneously claiming the same lease.

---

## Lease Ownership / Expiry / Takeover

### Lease Lifecycle

Each HA process holds a **process-unique instance ID** (UUID generated at startup, stored in an env var or temp file). A process acquires a **run-level lease** before performing any state-mutating operation:

```
ACQUIRE_LEASE(run_id, ttl=30s):
  INSERT INTO run_leases (run_id, owner_id, expires_at)
  VALUES ($run_id, $my_instance_id, NOW() + INTERVAL '30 seconds')
  ON CONFLICT (run_id) DO UPDATE
  SET owner_id = EXCLUDED.owner_id,
      expires_at = EXCLUDED.expires_at
  WHERE run_leases.owner_id = EXCLUDED.owner_id
     OR run_leases.expires_at < NOW();
  -- Returns: (acquired: bool, current_owner: str)
```

A standby process attempting to acquire an expired lease succeeds (its own `INSERT` overwrites the stale row). The standby then loads the run's state from `runs.run_data` and resumes from the latest checkpoint.

### Lease Heartbeat

The process actively working on a run refreshes the lease every **10 seconds** by re-issuing `ACQUIRE_LEASE` with the same `owner_id`. If a process dies, its leases expire after their TTL and are eligible for takeover by any standby.

### Leader Election for Standby Promotion

There is no global leader election. Each run is owned independently:

- **Active process:** Continuously renews its lease on runs it is actively working on.
- **Standby process:** Polls `run_leases` every 5 seconds for expired leases, acquires them, and resumes.

The standby only takes over runs whose `runs.state` is non-terminal (not in `TERMINAL_STATES = {FAILED, ABORTED, PLAN_RCA_RESOLVED}`). Terminal runs are never leased.

### Run-Start Serialization

`start_issue` uses `SELECT FOR UPDATE` on the issue-number row to prevent two processes from simultaneously creating duplicate `RunRecord` entries:

```python
-- Pessimistic lock on the issue number
BEGIN;
SELECT * FROM runs WHERE issue_number = $n FOR UPDATE;
-- If row exists: return existing run
-- If no row: INSERT new run, COMMIT
COMMIT;
```

---

## Delivery / Comment / Command Idempotency and Deterministic Ordering

### Idempotency Keys (ADR-009-1)

Webhook `X-GitHub-Delivery` IDs and GitHub comment IDs are stored in `runs.idempotency_keys` (a Postgres `TEXT[]`) and in `seen_delivery_keys`:

```python
async def start_issue(self, number: int, delivery_id: str | None = None) -> RunRecord:
    if delivery_id:
        # Fast path: check in-process cache first
        if delivery_id in self._seen_keys:
            return self.runs[number]   # idempotent skip

        # Cross-process: check Postgres
        exists = await self.pg.fetchval(
            "SELECT 1 FROM seen_delivery_keys WHERE delivery_id = $1", delivery_id
        )
        if exists:
            self._seen_keys.add(delivery_id)
            return self.runs[number]

        # Not seen: insert and proceed
        await self.pg.execute(
            "INSERT INTO seen_delivery_keys (delivery_id, run_id) VALUES ($1, $2)",
            delivery_id, run.run_id
        )
        self._seen_keys.add(delivery_id)
```

The same pattern applies to `command_outcomes` in `handle_comment`: the `comment_id` is checked in the `command_outcomes` JSONB column before executing any command.

### Deterministic Ordering

GitHub delivers webhooks at-least-once with no guaranteed ordering across concurrent deliveries. The **first-wins** policy (ADR-012) is preserved:

- `command_outcomes` tracks `RECEIVED → EXECUTING → CONFIRMED` state transitions.
- A command in `RECEIVED` or `EXECUTING` state is safe to **resume** (idempotent retry).
- A command in `CONFIRMED` state is **rejected** (already executed).

The CAS `revision` counter on `runs` provides a total order for all state transitions within a run: higher `revision` always means a later state.

---

## Evidence Integrity

The SHA-256 rolling hash chain (ADR-009-4) is preserved unchanged. Evidence is migrated from JSONL files to the `evidence` table:

```python
# On first startup with HA enabled, migrate existing JSONL files:
async def migrate_evidence_jsonl_to_pg(run_id: str) -> int:
    count = 0
    jsonl_path = Path(data_dir) / "evidence" / f"{run_id}.jsonl"
    if not jsonl_path.exists():
        return 0
    for line in jsonl_path.read_text().splitlines():
        rec = json.loads(line)
        await pg.execute("""
            INSERT INTO evidence (id, run_id, kind, payload, signature, idempotency_key)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (run_id, id) DO NOTHING
        """, rec["id"], run_id, rec["kind"], rec["payload"], rec["signature"], rec.get("idempotency_key"))
        count += 1
    return count
```

The `evidence` table stores the same fields as the JSONL records. The `list()`, `verify()`, and `checkpoint()` methods on `EvidenceStore` are updated to read from Postgres instead of the filesystem when `ha.enabled = true` in config.

Evidence integrity is verified by re-deriving the SHA-256 chain from the `signature` column in the `evidence` table. Any mismatch raises `MalformedEvidenceError` (existing behavior, ADR-009-4).

---

## Shared Anti-Replay / Rate-Limit State

The `rate_limit_buckets` table replaces the in-memory `SimpleRateLimiter` from ADR-014-2:

```python
async def check_rate_limit(key: str, limit: int, window_seconds: int = 3600) -> bool:
    """Return True if request is within rate limit, False if over limit."""
    now = datetime.now(UTC)
    window_start = now.replace(second=0, microsecond=0)

    row = await pg.fetchrow("""
        SELECT hits FROM rate_limit_buckets
        WHERE key = $1 AND window_start = $2 AND window_seconds = $3
        FOR UPDATE
    """, key, window_start, window_seconds)

    if row is None:
        await pg.execute(
            "INSERT INTO rate_limit_buckets VALUES ($1, 1, $2, $3)",
            key, window_start, window_seconds
        )
        return True

    if row["hits"] >= limit:
        return False

    await pg.execute(
        "UPDATE rate_limit_buckets SET hits = hits + 1 WHERE key = $1 AND window_start = $2",
        key, window_start
    )
    return True
```

A background task prunes expired rows (`DELETE FROM rate_limit_buckets WHERE window_start < NOW() - INTERVAL '2 hours'`) once per hour to bound table growth.

---

## Fail-Closed Readiness

The FastAPI `/health` and `/ready` endpoints change behavior when HA is enabled:

```python
@router.get("/health")
async def health():
    """Liveness probe — returns 200 if the process is alive."""
    return {"status": "ok"}

@router.get("/ready")
async def ready():
    """Readiness probe — fail-closed until Postgres is reachable and this process
    can verify it holds (or can acquire) its instance lease."""
    try:
        # 1. Verify Postgres connection
        await pg.fetchval("SELECT 1")

        # 2. Verify this instance's leases are valid
        rows = await pg.fetch(
            "SELECT run_id FROM run_leases WHERE owner_id = $1 AND expires_at > NOW()",
            INSTANCE_ID
        )
        return {"status": "ready", "active_leases": len(rows)}

    except Exception as e:
        raise HTTPException(status_code=503, detail=f"not ready: {e}")
```

If Postgres is unreachable, the readiness probe returns **503** and the load balancer health check fails. This prevents the load balancer from routing traffic to a process that cannot coordinate safely.

---

## Migrations and Rollback

### Migration Strategy

All schema changes go through Alembic migrations under `migrations/versions/`. Each migration is:

1. **Additive** (new tables, new nullable columns) — deployed first.
2. **Backfill** — run as a background job, not in the migration transaction.
3. **Breaking** (drop columns, rename) — only after all instances run the new code.

### Rollback Plan

If the HA migration must be reverted:

1. **Traffic:** Route all requests to the single legacy process.
2. **Data:** The Postgres data is **append-only** for evidence and idempotency keys. Run data is a full snapshot in `runs.run_data`. No data is destroyed by the HA layer — it is additive.
3. **Feature flag:** Set `ha.enabled = false` in `config/production.yaml`. The `HaRunStore` and `HaEvidenceStore` wrappers fall back to the existing `RunStore` / `EvidenceStore` filesystem implementations.
4. **Schema:** Drop HA tables in a follow-up migration. The filesystem data is untouched.

```python
# opsswarm/ha_store.py
class HaRunStore:
    """Adapter that delegates to filesystem store when HA is disabled."""

    def __init__(self, pg, data_dir: str, enabled: bool = True):
        self._pg = pg
        self._fs = RunStore(data_dir)   # existing impl
        self._enabled = enabled

    def save(self, run: RunRecord) -> None:
        if self._enabled:
            return self._save_pg(run)   # CAS + revision
        return self._fs.save(run)       # original behavior
```

---

## Operations Runbook

### Starting a New HA Deployment

1. Verify Postgres is reachable: `psql $DATABASE_URL -c "SELECT 1"`.
2. Run initial migration: `alembic upgrade head`.
3. Set `ha.enabled: true` in `config/production.yaml`.
4. Start process 1 (primary). Confirm readiness probe at `/ready` returns 200.
5. Start process 2 (standby). Confirm it starts in standby mode.

### Simulating Primary Failure

1. Send SIGTERM to the primary process.
2. Observe that standby acquires the expired leases within **30 seconds** (lease TTL).
3. Standby resumes non-terminal runs from the latest checkpoint in `checkpoints` table.
4. Verify via `SELECT owner_id, expires_at FROM run_leases` that standby now owns the leases.

### Manual Failover

```bash
# Force-release all leases held by the dead primary
psql $DATABASE -c "DELETE FROM run_leases WHERE owner_id = 'dead-instance-id'"
# The standby will immediately acquire these leases on its next poll
```

### Checking HA Health

```bash
# Active leases per instance
psql $DATABASE -c "SELECT owner_id, count(*) FROM run_leases GROUP BY owner_id"

# Runs in progress
psql $DATABASE -c "SELECT run_id, state, updated_at FROM runs WHERE state NOT IN ('RESOLVED','FAILED','ABORTED','PLAN_RCA_RESOLVED') ORDER BY updated_at DESC"

# Evidence chain integrity
psql $DATABASE -c "SELECT run_id, count(*) FROM evidence GROUP BY run_id ORDER BY count DESC LIMIT 10"
```

---

## Multi-Process Integration Tests

The following tests are **not yet implemented** but are specified here as acceptance criteria for the implementation phase:

### Test 1: Concurrent Webhook Delivery

```
Setup: Two processes (P1, P2) connected to same Postgres.
Action: Deliver the same X-GitHub-Delivery ID to both P1 and P2 simultaneously.
Expected: Exactly one RunRecord created; one evidence log entry appended.
```

### Test 2: Primary Crash + Standby Takeover

```
Setup: P1 actively working on a run in INVESTIGATING state.
Action: Kill P1 hard (SIGKILL).
Expected: P2 acquires the lease within 30s and resumes the run from the latest checkpoint.
```

### Test 3: Concurrent Command Execution

```
Setup: Two identical /opsswarm approve <option> comments delivered to different processes.
Expected: First-wins; second command is idempotently rejected; recovery action executes exactly once.
```

### Test 4: Evidence Chain Integrity Under Concurrency

```
Setup: Multiple processes appending evidence to the same run simultaneously.
Expected: No duplicate evidence; SHA-256 chain is unbroken in Postgres.
```

### Test 5: Readiness Probe Fail-Closed

```
Setup: Postgres unreachable.
Action: GET /ready
Expected: HTTP 503
```

### Test 6: Fallback to Filesystem When HA Disabled

```
Setup: ha.enabled = false; Postgres available.
Action: Process a webhook.
Expected: Filesystem store used; no Postgres tables written.
```

---

## Source Code Anchors

|| Concern | File | Current State |
|---|---|---|
| Run persistence | `opsswarm/store.py` | Atomic JSON files; no cross-process coordination |
| Evidence persistence | `opsswarm/evidence.py` | JSONL + per-run file lock; no cross-host safety |
| In-memory runs dict | `opsswarm/orchestrator.py:152` | `self.runs = {r.issue_number: r ...}` — unsynchronized across processes |
| Readiness probe | `opsswarm/api.py` | Returns 200 unconditionally; no coordination check |
| Rate limiting | `opsswarm/auth.py` | In-memory `SimpleRateLimiter`; not shared across processes |
| Idempotency | `opsswarm/orchestrator.py:376-390` | `idempotency_keys` on `RunRecord`; unsynchronized |
| Reconciliation | `opsswarm/reconciliation.py` | Loads from filesystem only |

---

## Alternatives Considered

|| Option | Description | Rejection Rationale |
|---|---|---|
| A — Postgres-backed coordination | This ADR — chosen | Best fit for existing infrastructure |
| B — Redis / BullMQ | Distributed queue + state | Not present in codebase; introduces new operational dependency |
| C — Leader election (Raft) | Embedded Raft consensus | Significant complexity; operational overhead; overkill for active/passive |
| D — Filesystem-only with flock | Keep JSON files, use NFS flock | NFS lock semantics vary across providers; not reliable for cross-host |
| E — Single-node only, no HA | Acknowledge limitation | Does not satisfy Issue #70 requirements |

---

## Implementation Phases

Implementation is divided into bounded phases. Each phase is a separate Kanban child task:

1. **Phase 1 — Postgres schema + migrations**: Alembic setup, `migrations/` directory, initial schema, down migration.
2. **Phase 2 — HaRunStore with CAS**: Replace `RunStore` with `HaRunStore`; `SELECT FOR UPDATE` for start_issue; `revision` counter; feature-flagged.
3. **Phase 3 — HaEvidenceStore migration**: Migrate JSONL evidence to Postgres; update `append()`, `list()`, `verify()` to use Postgres; backward-compatible JSONL read fallback.
4. **Phase 4 — Lease management + takeover**: `run_leases` table; instance ID generation; heartbeat thread; standby polling loop.
5. **Phase 5 — Shared rate limiting**: `rate_limit_buckets` table; replace `SimpleRateLimiter` with `PgRateLimiter`; config flag.
6. **Phase 6 — Fail-closed readiness**: Update `/health` and `/ready` probes; integration test suite (the 6 tests above).
7. **Phase 7 — Ops runbook + canary rollout**: Runbook documentation; gradual rollout with `ha.enabled` feature flag; rollback procedure validation.

Each phase is independently deployable and reversible via the feature flag `ha.enabled`.

---

## Compatibility and Migration

- **Backwards compatible:** All existing behavior is preserved when `ha.enabled = false` (default). No existing tests break.
- **Data migration:** JSONL evidence is read on first access and migrated lazily. Run records are migrated on first write.
- **Rollback:** Set `ha.enabled = false`. The `HaRunStore` / `HaEvidenceStore` wrappers fall back to filesystem implementations transparently.
- **Zero-downtime upgrade:** Add Postgres schema (migration 1) → deploy new code with `ha.enabled: false` → enable HA feature flag → zero-impact.
