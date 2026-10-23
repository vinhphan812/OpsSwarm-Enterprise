# HA Coordination Runbook

**ADR Reference:** [ADR-030 — High-Availability Multi-Process Coordination](../adr/ADR-030_HA_COORDINATION.md)  
**Issue:** #70  
**Phases:** 1–7 (this document covers Phase 7)

---

## Table of Contents

1. [Overview](#overview)
2. [Configuration Reference](#configuration-reference)
3. [Starting a New HA Deployment](#starting-a-new-ha-deployment)
4. [Simulating Primary Failure](#simulating-primary-failure)
5. [Manual Failover](#manual-failover)
6. [HA Health Checks](#ha-health-checks)
7. [Rollback Procedure](#rollback-procedure)
8. [Schema Migrations](#schema-migrations)
9. [Canary Rollout Procedure](#canary-rollout-procedure)
10. [Evidence Migration](#evidence-migration)

---

## Overview

OpsSwarm HA uses an **active/passive** topology with PostgreSQL as the coordination store.
When `ha.enabled = true`, all run state, evidence, and rate-limit state are stored in Postgres
with compare-and-swap (CAS) revision counters and per-run leases. When `ha.enabled = false`
(the default), the system falls back to the filesystem-based `RunStore` / `EvidenceStore`
with zero data loss.

```
┌──────────────────┐         ┌──────────────────┐
│  Primary (P1)    │         │  Standby (P2)     │
│  ha.enabled=true │         │  ha.enabled=true  │
│  holds leases    │         │  polls for expired │
│                  │◄───────►│  leases           │
└────────┬─────────┘  PgSQL  └────────┬─────────┘
         │                  ▲        │
         │                  │        │
    filesystem            WAL    filesystem
    evidence/.jsonl        DB     evidence/.jsonl
    (fallback reads)              (fallback reads)
```

### Key Parameters (ADR-030)

| Parameter | Value | Rationale |
|---|---|---|
| Lease TTL | 30 s | Enough for graceful takeover; short enough to detect failures quickly |
| Heartbeat interval | 10 s | 3× heartbeat before lease expires |
| Standby poll interval | 5 s | Latency budget for takeover |
| Terminal states | `RESOLVED`, `FAILED`, `ABORTED`, `PLAN_RCA_RESOLVED` | Standby never leases terminal runs |

---

## Configuration Reference

### `config/production.yaml`

```yaml
ha:
  enabled: false          # default false — backward-compatible; set true to activate HA
  database_url: ${HA_DATABASE_URL}   # psycopg2 connection string
  lease_ttl_seconds: 30
  heartbeat_interval_seconds: 10
  standby_poll_interval_seconds: 5
```

Set `HA_DATABASE_URL` in the environment before starting the process.

### Feature Flag Behavior

| `ha.enabled` | Behavior |
|---|---|
| `false` (default) | `RunStore` / `EvidenceStore` use filesystem. All existing tests pass. `/ready` returns 200 unconditionally. |
| `true` | `HaRunStore` / `HaEvidenceStore` use Postgres. `/ready` fails-closed until Postgres is reachable and this instance has verified its leases. |

---

## Starting a New HA Deployment

### Prerequisites

- PostgreSQL ≥ 14 accessible from all hosts.
- Network connectivity between primary and standby on the Postgres port.
- `ha.enabled: true` set in `config/production.yaml` on both instances.

### Procedure

```bash
# 1. Verify Postgres connectivity from each host
psql "$HA_DATABASE_URL" -c "SELECT 1"
# Expected:  ?column?
#                   1
# (1 row)

# 2. Run initial schema migration (idempotent — safe to re-run)
alembic upgrade head
# Expected output:
#   INFO  [alembic.runtime.migration] Running upgrade  -> 001_initial_ha_schema
#   INFO  [alembic.runtime.migration] Running upgrade 001_initial_ha_schema (none) -> (head)

# 3. Verify all 6 tables were created
psql "$HA_DATABASE_URL" -c "\dt" | grep -E "runs|run_leases|evidence|checkpoints|rate_limit_buckets|seen_delivery_keys"
# Expected: 6 rows

# 4. Start the primary process
OPSWARM_CONFIG=config/production.yaml \
  HA_DATABASE_URL="$HA_DATABASE_URL" \
  uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088

# 5. Wait for readiness probe — verify it returns 200 with active_leases
curl -s http://localhost:8088/ready | python -m json.tool
# Expected:
# {
#     "status": "ready",
#     "active_leases": 0
# }

# 6. In a separate terminal, start the standby process (same config, different host/port)
OPSWARM_CONFIG=config/production.yaml \
  HA_DATABASE_URL="$HA_DATABASE_URL" \
  uvicorn opsswarm.api:app --host 0.0.0.0 --port 8089

# 7. Verify standby is polling but not holding leases
psql "$HA_DATABASE_URL" -c "SELECT owner_id, count(*) FROM run_leases GROUP BY owner_id"
# Expected: either empty (no runs started yet) or shows primary's instance ID

# 8. Confirm evidence table is empty (no legacy migration yet)
psql "$HA_DATABASE_URL" -c "SELECT count(*) FROM evidence"
# Expected: 0
```

### Startup Order

Always start the primary first. The standby starts in polling mode and will not acquire
leases until runs exist with expired leases.

```
primary startup → acquires run_leases → processes webhook → writes evidence
standby startup → polls run_leases every 5s → takes over when leases expire
```

---

## Simulating Primary Failure

### Procedure

```bash
# 1. Start a workload on the primary (e.g., create a run via webhook delivery)
#    Confirm a non-terminal run exists:
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, state, owner_id FROM runs WHERE state NOT IN ('RESOLVED','FAILED','ABORTED')"

# 2. Confirm primary holds the lease for that run
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, owner_id, expires_at FROM run_leases WHERE run_id = '<run_id>'"
# Expected: owner_id = primary instance ID, expires_at ≈ NOW + 30s

# 3. Simulate primary failure — send SIGTERM to the primary process
#    On the primary host:
kill -TERM <primary_pid>
# Or for SIGKILL (hard crash simulation):
kill -KILL <primary_pid>

# 4. Observe standby takeover — wait up to 30 seconds (lease TTL)
#    Check from any host:
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, owner_id, expires_at FROM run_leases WHERE run_id = '<run_id>'"
# Expected: owner_id = standby instance ID, expires_at refreshed

# 5. Verify run state is intact (no data corruption)
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, state, updated_at FROM runs WHERE run_id = '<run_id>'"
# Expected: state = previous non-terminal state, updated_at refreshed by standby

# 6. Verify evidence chain is unbroken
psql "$HA_DATABASE_URL" -c \
  "SELECT id, run_id, signature, event_timestamp FROM evidence WHERE run_id = '<run_id>' ORDER BY event_timestamp"
# Expected: all previous evidence present, SHA-256 chain intact

# 7. Verify checkpoint resume point
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, checkpoint_type, sequence, created_at FROM checkpoints WHERE run_id = '<run_id>' ORDER BY sequence DESC LIMIT 1"
# Expected: latest checkpoint present, sequence number matches standby's resume point
```

### Expected Outcomes

| Check | Pass Criteria |
|---|---|
| Lease transferred | Standby `owner_id` appears in `run_leases` within 30 s |
| State preserved | `runs.state` unchanged; `runs.revision` incremented |
| Evidence intact | All `evidence` rows present; no duplicate IDs |
| Checkpoint loaded | Latest checkpoint matches standby's resume point |
| `/ready` on standby | Returns 200 with `active_leases > 0` |

---

## Manual Failover

Use this when the primary has crashed and the standby has not yet picked up the leases
(e.g., standby is down, or you need to force release a known-dead instance's leases).

### Force-Release Leases for a Dead Instance

```bash
# Identify the dead instance's owner_id (from logs, env, or process inspection)
DEAD_INSTANCE_ID="<instance-id-from-primary-logs>"

# Force-release all leases held by the dead instance
psql "$HA_DATABASE_URL" -c \
  "DELETE FROM run_leases WHERE owner_id = '$DEAD_INSTANCE_ID'"

# Verify all leases are gone
psql "$HA_DATABASE_URL" -c "SELECT count(*) AS remaining_leases FROM run_leases"

# The standby will immediately acquire these leases on its next poll (≤ 5 s)
psql "$HA_DATABASE_URL" -c \
  "SELECT owner_id, count(*) FROM run_leases GROUP BY owner_id"
# Expected: standby instance ID holds all previously-owned leases
```

### Verify Manual Failover Success

```bash
# Confirm all non-terminal runs are owned by the standby
psql "$HA_DATABASE_URL" -c \
  "SELECT r.run_id, r.state, l.owner_id, l.expires_at \
   FROM runs r LEFT JOIN run_leases l ON r.run_id = l.run_id \
   WHERE r.state NOT IN ('RESOLVED','FAILED','ABORTED') \
   ORDER BY r.updated_at DESC"

# Expected: every non-terminal run has a row in run_leases
#           with standby's owner_id and a future expires_at
```

---

## HA Health Checks

Run these queries against `$HA_DATABASE_URL` to assess cluster health.

### Active Leases Per Instance

```bash
psql "$HA_DATABASE_URL" -c \
  "SELECT owner_id, count(*) AS lease_count, \
          min(expires_at) AS earliest_expiry, \
          max(expires_at) AS latest_expiry \
   FROM run_leases \
   GROUP BY owner_id \
   ORDER BY lease_count DESC"
```

**Healthy state:** One or two `owner_id` values; `earliest_expiry` is at least 10 s in the future.

**Warning state:** `earliest_expiry` is within 10 s — heartbeat may be stalled.

**Critical state:** All leases have expired (no output) — primary is down and standby hasn't taken over.

### Runs in Progress

```bash
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, issue_number, state, revision, updated_at \
   FROM runs \
   WHERE state NOT IN ('RESOLVED','FAILED','ABORTED','PLAN_RCA_RESOLVED') \
   ORDER BY updated_at DESC \
   LIMIT 20"
```

**Check:** Every active run should have a corresponding row in `run_leases`.

### Orphaned Runs (No Lease)

```bash
psql "$HA_DATABASE_URL" -c \
  "SELECT r.run_id, r.state, r.updated_at \
   FROM runs r \
   WHERE r.state NOT IN ('RESOLVED','FAILED','ABORTED','PLAN_RCA_RESOLVED') \
     AND r.run_id NOT IN (SELECT run_id FROM run_leases)"
```

**Action required:** Either start a standby to pick them up, or manually close the run.

### Evidence Chain Integrity

```bash
# Row count per run (top 10 noisiest)
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, count(*) AS evidence_count, \
          min(event_timestamp) AS first_event, \
          max(event_timestamp) AS last_event \
   FROM evidence \
   GROUP BY run_id \
   ORDER BY evidence_count DESC \
   LIMIT 10"

# Verify signature chain continuity (sample one run)
psql "$HA_DATABASE_URL" -c \
  "SELECT id, signature, event_timestamp \
   FROM evidence \
   WHERE run_id = '<run_id>' \
   ORDER BY event_timestamp \
   LIMIT 5"
```

**Action required if broken:** See Evidence Migration section below for recovery procedure.

### Rate Limit Bucket Health

```bash
# Bucket hit distribution
psql "$HA_DATABASE_URL" -c \
  "SELECT key, hits, window_start, window_seconds, \
          (window_start + (window_seconds || ' seconds')::interval) AS window_end \
   FROM rate_limit_buckets \
   ORDER BY hits DESC \
   LIMIT 20"

# Stale buckets (past 2-hour retention window)
psql "$HA_DATABASE_URL" -c \
  "SELECT count(*) AS stale_buckets \
   FROM rate_limit_buckets \
   WHERE window_start < NOW() - INTERVAL '2 hours'"
# If > 0, run the background prune: DELETE FROM rate_limit_buckets WHERE window_start < NOW() - INTERVAL '2 hours'
```

### Readiness Probe Verification

```bash
# From each host running the process:
curl -s http://localhost:8088/ready
# Pass:  {"status": "ready", "active_leases": N}
# Fail:  HTTP 503 — Postgres unreachable or lease verification failed

# Verify Postgres is the bottleneck (not the process):
psql "$HA_DATABASE_URL" -c "SELECT 1"
```

---

## Rollback Procedure

Rollback means reverting to the filesystem store without data loss.

### Step-by-Step Rollback

```bash
# 1. Route all traffic away from HA instances (load balancer config)
#    Ensure only one legacy process is receiving webhooks.

# 2. Confirm no new Postgres writes are occurring
psql "$HA_DATABASE_URL" -c \
  "SELECT max(updated_at) AS last_write FROM runs"
# Note the timestamp. If updates are still happening, wait.

# 3. Set feature flag to false (do NOT restart yet)
#    Edit config/production.yaml:
#    ha:
#      enabled: false    # <— flip this

# 4. Restart the process (or send SIGHUP to reload config)
kill -HUP <pid>
# Alternatively: restart the uvicorn process with the updated config.

# 5. Verify filesystem store is active
curl -s http://localhost:8088/ready
# Expected: HTTP 200 {"status": "ok"} (legacy unconditional 200)

# 6. Confirm zero filesystem data corruption — verify existing run files are readable
ls runtime-data/runs/*.json | wc -l
# Expected: ≥ count of non-terminal runs from step 2

# 7. Verify evidence JSONL files are intact
wc -l runtime-data/evidence/*.jsonl
# Expected: all files present and readable

# 8. Process one test webhook — verify it writes to filesystem, not Postgres
psql "$HA_DATABASE_URL" -c "SELECT max(updated_at) FROM runs"  # note timestamp
# Send a test webhook
sleep 2
psql "$HA_DATABASE_URL" -c "SELECT max(updated_at) FROM runs"
# Expected: timestamp unchanged (no new Postgres writes)

# 9. (Optional) Drop HA tables — run as a separate migration in a maintenance window
#    The tables are append-only; dropping them does not affect filesystem data.
alembic downgrade -1
# Expected:
#   INFO  [alembic.runtime.migration] Running downgrade 001_initial_ha_schema -> (head)
```

### Data Integrity Guarantee

The HA layer is **additive only**:
- `runs.run_data` is a full snapshot of the RunRecord — no data is lost by dropping the row.
- `evidence` rows are append-only mirrors of the JSONL files.
- `seen_delivery_keys` is idempotent — a second delivery with the same key is harmless.
- Filesystem data is never modified or deleted by the HA layer.

---

## Schema Migrations

All schema changes go through Alembic. Migrations live in `migrations/versions/`.

### Key Commands

```bash
# Show current migration revision
alembic current
# Example output: 001_initial_ha_schema

# Show migration history
alembic history --verbose

# Upgrade to head (apply all pending migrations)
alembic upgrade head

# Downgrade one step (rollback last migration)
alembic downgrade -1

# Downgrade to a specific revision
alembic downgrade <revision>

# Stamp current state without running migrations (after manual schema edit)
alembic stamp head

# Validate migration chain (check for gaps)
alembic check
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `HA_DATABASE_URL` | Yes (when HA enabled) | `postgresql://user:pass@host:5432/dbname` |
| `OPSWARM_CONFIG` | No | Path to config file (default: `config/production.yaml`) |

### Migration Conventions

1. **Additive migrations first** — new tables and nullable columns are safe to deploy before code.
2. **Backfill as background jobs** — do not backfill inside the migration transaction.
3. **Breaking changes only after full rollout** — drop columns/tables only after all instances run new code.
4. **Test rollback locally** — always run `alembic downgrade -1` and `alembic upgrade head` before merging.

### Initial Schema (001_initial_ha_schema)

The initial migration creates all 6 HA tables:

| Table | Purpose |
|---|---|
| `runs` | Run state with CAS revision counter |
| `run_leases` | Per-run leadership lease with TTL |
| `evidence` | Append-only evidence log with SHA-256 chain |
| `checkpoints` | Run checkpoint snapshots for standby resume |
| `rate_limit_buckets` | Shared token-bucket rate limiting |
| `seen_delivery_keys` | Webhook idempotency deduplication |

---

## Canary Rollout Procedure

A canary rollout validates HA incrementally with `ha.enabled` as the feature flag.

### Phase 0 — Baseline (ha.enabled = false)

```bash
# Default state — all existing tests pass
make ci
# Expected: lint ✓  typecheck ✓  pytest ✓  coverage ≥ 90%  build ✓

# Confirm /ready is unconditional 200
curl -s -o /dev/null -w "%{http_code}" http://localhost:8088/ready
# Expected: 200
```

### Phase 1 — Schema Deployment (ha.enabled = false)

```bash
# Deploy new code with ha.enabled = false (legacy mode)
# Run migration — no downtime, no behavioral change
alembic upgrade head
# Expected: 6 tables created, no data affected

# Verify no tables are written to during legacy mode
# (watch in another terminal)
watch -n1 'psql "$HA_DATABASE_URL" -c "SELECT count(*) FROM runs"'
# Expected: count stays at 0 (no new rows in legacy mode)

# Run full test suite — must still pass
make ci
# Expected: all green
```

### Phase 2 — HA Enable in Staging (ha.enabled = true)

```bash
# Set flag in staging config
# config/staging.yaml:
#   ha:
#     enabled: true
#     database_url: ${HA_DATABASE_URL}

# Start staging process
OPSWARM_CONFIG=config/staging.yaml HA_DATABASE_URL="$STAGING_DB_URL" \
  uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088 &

# Wait for readiness probe
sleep 5
curl -s http://localhost:8088/ready
# Expected: {"status": "ready", "active_leases": 0}

# Run full test suite against staging
make test
# Expected: all tests pass

# Verify evidence migration (see next section)
```

### Phase 3 — Verify Evidence Migration

```bash
# With HA enabled, existing JSONL evidence must remain readable
# List all existing evidence files
ls runtime-data/evidence/*.jsonl

# Trigger evidence migration for each run
# (The implementation lazily migrates on first access, but you can force it:)
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id FROM runs WHERE run_id IN \
   (SELECT DISTINCT run_id FROM evidence)"

# Verify migration count
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, count(*) AS evidence_rows FROM evidence GROUP BY run_id ORDER BY count DESC"

# Verify JSONL files are still readable and identical in content
# (the HA layer falls back to JSONL if Postgres has no records for a run)
```

### Phase 4 — Rollback Validation in Staging

```bash
# Disable HA
# config/staging.yaml:
#   ha:
#     enabled: false

# Restart process
kill -HUP <staging_pid>

# Verify /ready returns unconditional 200
curl -s -o /dev/null -w "%{http_code}" http://localhost:8088/ready
# Expected: 200

# Verify filesystem store resumed
psql "$STAGING_DB_URL" -c "SELECT max(updated_at) FROM runs"  # note timestamp
# Send test webhook
sleep 2
psql "$STAGING_DB_URL" -c "SELECT max(updated_at) FROM runs"
# Expected: timestamp unchanged

# Verify existing run files are intact
ls runtime-data/runs/*.json | wc -l
# Expected: ≥ previous count
```

### Phase 5 — Production Rollout

```bash
# 1. Schedule maintenance window (brief)
# 2. Enable HA in production config
# 3. Run alembic upgrade head
# 4. Start primary
# 5. Verify /ready returns 200
# 6. Start standby
# 7. Monitor for 15 minutes
# 8. If healthy: complete rollout. If not: rollback immediately.
```

---

## Evidence Migration

On first startup with `ha.enabled = true`, the `HaEvidenceStore` lazily migrates
existing JSONL files to Postgres. The migration is **idempotent** (uses `ON CONFLICT DO NOTHING`).

### Migration Entry Point

```python
# Triggered automatically on first evidence access for each run:
async def migrate_evidence_jsonl_to_pg(run_id: str) -> int:
    jsonl_path = Path(data_dir) / "evidence" / f"{run_id}.jsonl"
    if not jsonl_path.exists():
        return 0
    count = 0
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        await pg.execute("""
            INSERT INTO evidence (id, run_id, kind, payload, signature, idempotency_key)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (run_id, id) DO NOTHING
        """, rec["id"], run_id, rec["kind"], rec["payload"],
           rec["signature"], rec.get("idempotency_key"))
        count += 1
    return count
```

### Verify Evidence Migration

```bash
# Count evidence rows per run
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, count(*) AS pg_count FROM evidence GROUP BY run_id ORDER BY pg_count DESC"

# Compare with JSONL line counts
for f in runtime-data/evidence/*.jsonl; do
  echo "$f: $(wc -l < "$f") lines"
done

# Expected: pg_count matches or exceeds JSONL line count
# (pg may have additional rows appended after migration)
```

### Rollback of Evidence Migration

Since evidence migration is append-only and idempotent, rollback requires no action:
- JSONL files are never deleted or modified.
- When `ha.enabled = false`, `EvidenceStore` reads from JSONL files directly.
- To re-migrate from scratch: `DELETE FROM evidence WHERE run_id = '<run_id>'` then restart.

---

## Troubleshooting

### `/ready` returns 503

```bash
# 1. Verify Postgres is reachable
psql "$HA_DATABASE_URL" -c "SELECT 1"

# 2. Verify this instance's leases
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, expires_at FROM run_leases WHERE owner_id = '$INSTANCE_ID'"

# 3. Check process logs for connection errors
#    Look for: "connection refused", "password authentication failed", "certificate verify failed"

# 4. If Postgres is down: restore it before HA can work
#    HA is fail-closed by design — 503 is the correct response when Postgres is unavailable
```

### Standby not taking over leases

```bash
# 1. Verify standby is running and connected
psql "$HA_DATABASE_URL" -c \
  "SELECT application_name, state, state_change_age \
   FROM pg_stat_activity \
   WHERE application_name LIKE '%uvicorn%'"

# 2. Check standby poll interval (should be ≤ 5 s)
#    Verify: ha.standby_poll_interval_seconds = 5 in config

# 3. Manually release dead leases
psql "$HA_DATABASE_URL" -c \
  "DELETE FROM run_leases WHERE expires_at < NOW() - INTERVAL '5 seconds'"

# 4. Verify standby acquires immediately after manual release
sleep 6
psql "$HA_DATABASE_URL" -c \
  "SELECT owner_id, count(*) FROM run_leases GROUP BY owner_id"
```

### Duplicate evidence rows

```bash
# Check for duplicate (run_id, id) pairs
psql "$HA_DATABASE_URL" -c \
  "SELECT run_id, id, count(*) FROM evidence \
   GROUP BY run_id, id HAVING count(*) > 1"

# If duplicates exist: evidence chain may be broken
# Re-verify chain from JSONL:
# 1. DELETE FROM evidence WHERE run_id = '<run_id>'
# 2. Re-trigger migration by accessing evidence for that run
```

### Alembic migration fails

```bash
# 1. Check current state
alembic current

# 2. Show full history
alembic history --verbose

# 3. If DB is at an unexpected state, stamp manually
alembic stamp 001_initial_ha_schema  # set stamp without running migrations

# 4. If tables already exist, migration may be out of sync
#    Run with --sql to see what would be executed:
alembic upgrade head --sql > migration.sql
#    Review migration.sql before applying
```
