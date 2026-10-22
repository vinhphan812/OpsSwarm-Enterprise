# ADR-031: High-Availability Multi-Process Coordination

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

Production deployments increasingly require multi-host HA — either active/active (multiple processes serving webhooks simultaneously) or active/passive (a warm standby that takes over on primary failure under an explicit operator authorisation). This ADR defines the coordination layer that makes that safe.

## Policy Decision

**Adopt a PostgreSQL-backed coordination layer as the single source of truth for cross-process state.**

The rationale for PostgreSQL over alternatives:

| Property | PostgreSQL | Redis | In-memory (current) |
|---|---|---|---|
| Cross-host coordination | ✅ via TCP | ✅ | ❌ |
| Durable writes | ✅ (WAL) | optional (AOF/RDB) | ❌ |
| Existing infrastructure | **Assumption** — a managed PostgreSQL 14+ service must be provided by the deployment; not verified by this repository | Requires separate deployment | N/A |
| Transactional CAS | ✅ (`SELECT FOR UPDATE`) | Lua + WATCH | ❌ |
| Schema migration tooling | ✅ (Alembic) | N/A | N/A |
| No new infrastructure | **Assumption / required deployment dependency, not a verified fact** — see "Operator prerequisites for the PostgreSQL dependency" | ❌ | N/A |
| Codebase evidence | Not present — this ADR introduces it | Not present — excluded from scope | Current state |

**Scope exclusion (no Redis):** No part of this ADR references BullMQ, Redis, or any message-queue infrastructure unless evidence of such usage appears in the codebase first.

**Bounded HA guarantee:** OpsSwarm HA is bounded to **active/passive with operator-authorised failover** for the initial implementation phase. Active/active (multiple processes serving webhooks simultaneously) is explicitly deferred to a future ADR.

### Operator prerequisites for the PostgreSQL dependency (assumption, not evidence)

The comparison table above records an **assumption**, not a verified fact. This repository contains
no PostgreSQL implementation, no driver dependency, no migration, and no deployment
descriptor. The design in this ADR can only be exercised once an operator provides all of the
following. Until then, HA remains Proposed and `ha.enabled` is not an accepted production claim:

1. A managed PostgreSQL 14+ service with a primary writer and a hot standby replica in a
   different failure domain, exposed through a single writer endpoint.
2. WAL archiving and point-in-time recovery enabled, with `synchronous_commit` covering at
   least one designated synchronous standby for coordination writes.
3. A credential (or workload identity) granting the OpsSwarm service account DDL ownership of
   the coordination schema during migration and DML rights at runtime; secrets are supplied
   through the environment and never committed.
4. A bounded connection-pool policy with a distinct `application_name`, connect timeout, and
   documented behaviour on database promotion (discard and reacquire connections).
5. Network reachability from every OpsSwarm process to the writer endpoint, with the standby
   permitted to fail closed when that reachability is lost.
6. An operator able to grant, and to audit, a failover authorisation (see "Failover policy").

A team that cannot supply items 1–6 must either provision them or keep `ha.enabled = false`;
this ADR does not assume that the operational platform already provides them.

### Failover policy (initial phase)

**Decision: active/passive with operator-authorised failover. Takeover of an expired lease is
never automatic in the initial phase.**

The previous revision of this ADR stated both "manual failover" and "the standby polls leases
every 5 seconds and automatically acquires expired leases". Those two statements are
contradictory and are replaced by the single policy below.

- **Who authorises.** A named human operator (the incident commander for the affected
  incident, or the on-call operator delegated for the deployment) authorises failover for a
  specific set of runs. Free-text comments, agent recommendations, and automatic retry
  behaviour are **not** authorisation, consistent with the project's governance principle that
  free text never authorises side effects.
- **How authorisation is recorded.** The authorisation is recorded durably in the
  coordination schema as a `lease_takeover_authorisations` row carrying the run identifier,
  the lease epoch observed at authorisation time, the approving operator identity, the
  timestamp, and the reason. The record is written by an audited operator action, not by the
  standby.
- **What the standby does before authorisation.** The standby polls `run_leases` on a bounded
  interval to *observe* eligibility (an expired lease on a non-terminal run). It may not
  acquire, dispatch, or resume any such run. It keeps its own local readiness gate closed for
  mutable admission of that run, and it does not delete or rewrite the expired lease row.
- **What the standby does after authorisation.** When a matching authorisation exists, the
  standby performs the normal acquisition transaction: it takes the lease row `FOR UPDATE`,
  increments the epoch, and commits. Only then does it reload durable state and resume from
  the latest checkpoint.
- **Fencing gate.** The acquisition increments `epoch` in the same transaction that changes
  `owner_id`. Any holder of an older epoch that subsequently attempts a protected write is
  rejected with `StaleEpochError` and commits nothing.
- **Replay gate.** After a successful takeover the standby must reload durable run state and
  must not re-issue an external side effect whose intent record is unresolved. The standby
  enters the reconciliation path in "External Side-Effect Intent and Outcome Reconciliation"
  instead of retrying the write.
- **Stale authorisations.** An authorisation is bound to the epoch observed when it was
  granted. If the lease epoch has changed since, the authorisation no longer applies and a
  fresh authorisation is required. This prevents an authorisation issued for one generation
  from being applied to a later one.

Automatic takeover (standby acquisition on expiry without operator authorisation) is
explicitly **not** in scope for the initial phase. It may only be considered in a later ADR
that also supplies quorum-based membership or an equivalent proof that a former leader is
dead; until then it would reintroduce the external side-effect window that the fencing and
replay gates exist to bound.

---

## Single-Node vs HA Supported Guarantees

| Scenario | Single-node (current) | HA — active/passive (this ADR) |
|---|---|---|
| Process crash + restart | Recovered via checkpoints (ADR-009-3) | Same; after operator-authorised failover the standby resumes from the same persisted state at an incremented epoch |
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

-- Run leadership lease and durable fencing token
CREATE TABLE run_leases (
    run_id      TEXT        NOT NULL PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    owner_id    TEXT        NOT NULL,           -- process-unique instance ID
    epoch       BIGINT      NOT NULL DEFAULT 1, -- monotonically increasing fencing token
    expires_at  TIMESTAMPTZ NOT NULL,
    CONSTRAINT  run_leases_epoch_positive CHECK (epoch > 0)
    -- Note: expires_at > NOW() is intentionally omitted as a table CHECK constraint.
    -- PostgreSQL CHECK constraints are evaluated strictly on INSERT or UPDATE of the
    -- row itself, not continuously as wall-clock time advances. A static CHECK constraint
    -- would become false as soon as the lease expires in the background, preventing any
    -- subsequent UPDATE (such as a renewal or takeover) from executing on the expired row.
    -- Expiry is instead enforced dynamically in acquisition and renewal SQL statements
    -- using PostgreSQL server time (NOW()) inside transactions with FOR UPDATE row locks.
);

-- Operator authorisation for failover takeover (recorded by an audited operator action,
-- never by the standby itself). Bound to the epoch observed at authorisation time so a
-- stale authorisation cannot be applied to a later lease generation.
CREATE TABLE lease_takeover_authorisations (
    run_id          TEXT        NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    observed_epoch  BIGINT      NOT NULL,        -- lease epoch at the time of authorisation
    approved_by     TEXT        NOT NULL,        -- human operator identity
    reason          TEXT        NOT NULL,
    authorised_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_epoch  BIGINT,                      -- epoch granted when the takeover happened
    PRIMARY KEY (run_id, observed_epoch)
);

-- Durable intent/outcome records for external GitHub side effects that epoch fencing
-- cannot revoke. The intent row is written BEFORE the outbound HTTP call; the outcome
-- is written AFTER. An intent with no matching outcome is an ambiguous in-flight
-- side effect and is reconciled rather than blindly retried.
CREATE TABLE external_side_effect_intents (
    intent_key      TEXT        NOT NULL,        -- idempotency / command key
    run_id          TEXT        NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    epoch           BIGINT      NOT NULL,        -- lease epoch of the issuing leader
    operation       TEXT        NOT NULL,        -- e.g. issue_comment, remediation_pr
    target_ref      TEXT        NOT NULL,        -- e.g. issue number or PR reference
    request_digest  TEXT        NOT NULL,        -- digest of the outbound request payload
    state           TEXT        NOT NULL,        -- INTENDED | CONFIRMED | FAILED | AMBIGUOUS
    outcome_detail  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    PRIMARY KEY (intent_key)
);

CREATE INDEX idx_side_effect_intents_run ON external_side_effect_intents (run_id, state);

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

## Lease Ownership, Epoch Fencing, Expiry, and Takeover

### Epoch fencing contract

A lease is not sufficient protection against a delayed former leader. Every `run_leases` row
therefore carries a durable, strictly increasing **epoch** (a fencing token). PostgreSQL is
the authority for both lease expiry and the next epoch; application-host clocks are never used
to decide ownership.

- The first successful owner of a run receives epoch `1`. A renewal by the same `owner_id`
  preserves that epoch. Every successful takeover by a different owner increments it in the
  same row-locking transaction that changes `owner_id`.
- The acquisition transaction returns `(owner_id, epoch, expires_at)`. The holder must retain
  that epoch and present it in every protected mutation. Losing a renewal, observing a higher
  epoch, or receiving a zero-row update is terminal for that holder's mutable work: it must
  stop dispatching and reload state; it must not retry the write under its stale epoch.
- The protected write paths are: (1) command dispatch and its `command_outcomes` transition,
  including any remediation action; (2) GitHub issue/comment/remediation writes and their
  evidence append; (3) webhook-driven run-state and idempotency transitions; (4) checkpoint
  and run-state CAS updates. Read-only investigation and `/health` are not leadership writes.
- Each protected transaction locks or conditionally joins the current `run_leases` row and
  requires `owner_id = $owner_id`, `epoch = $epoch`, and `expires_at > NOW()` before mutating
  `runs`, `evidence`, `checkpoints`, or delivery/command state. A mismatch returns a defined
  `StaleEpochError` and commits no protected mutation. External GitHub calls are preceded by
  that transaction/validation, recorded with the epoch and idempotency key, then reconciled by
  the durable first-wins command outcome; no external call is asserted safe merely because an
  in-memory lease looked valid.

The ordering guarantee is therefore database-enforced: after epoch `N+1` has been granted for
a run, a holder carrying any epoch `< N+1` cannot commit a protected database write. Epochs
fence durable OpsSwarm writes; they cannot retract an HTTP request that a stale holder sent
before it learned it was fenced. Idempotency keys, command outcomes, and reconciliation limit
that residual external-side-effect window.

### Lease Lifecycle

Each HA process holds a **process-unique instance ID** (UUID generated at startup, stored in an env var or temp file). A process acquires a **run-level lease** before performing any protected mutation:

```
ACQUIRE_LEASE(run_id, ttl=30s, authorisation_epoch=None):
  BEGIN;
  SELECT owner_id, epoch, expires_at
  FROM run_leases WHERE run_id = $run_id FOR UPDATE;
  -- if absent: INSERT (..., owner_id=$me, epoch=1, expires_at=NOW()+30s)
  -- if current owner is $me: renew expiry, preserving epoch
  -- if expired: takeover requires a matching lease_takeover_authorisations row
  --   (authorisation.observed_epoch = current epoch); on takeover:
  --   UPDATE owner_id=$me, epoch=epoch+1, expires_at=NOW()+30s
  --   and UPDATE lease_takeover_authorisations SET consumed_epoch=epoch+1
  -- otherwise: return not acquired with the current owner and epoch
  COMMIT;
  -- Returns: (acquired, owner_id, epoch, expires_at)
```

**Expiry is enforced in the SQL, not in a table constraint.** The acquisition and renewal
statements compare `expires_at` against PostgreSQL server time (`NOW()`) inside the same
transaction that holds the `FOR UPDATE` row lock, so the decision is serialised and uses the
database clock rather than any application-host clock:

```sql
-- Renewal by the current owner, refused when the lease has already expired
UPDATE run_leases
SET    expires_at = NOW() + INTERVAL '30 seconds'
WHERE  run_id     = $run_id
  AND  owner_id   = $me
  AND  epoch      = $epoch
  AND  expires_at > NOW();   -- dynamic expiry test using PostgreSQL server time
-- rowcount == 0 → the lease has expired or been taken over; stop protected work
```

```sql
-- Takeover of an expired lease, permitted only with a matching operator authorisation
UPDATE run_leases l
SET    owner_id   = $me,
       epoch      = l.epoch + 1,
       expires_at = NOW() + INTERVAL '30 seconds'
FROM lease_takeover_authorisations a
WHERE l.run_id         = $run_id
  AND a.run_id         = l.run_id
  AND a.observed_epoch = l.epoch      -- authorisation is bound to this generation
  AND a.consumed_epoch IS NULL        -- not already used
  AND l.expires_at     <= NOW()        -- dynamic expiry test using PostgreSQL server time
RETURNING l.owner_id, l.epoch, l.expires_at;
```

A standby process attempting to acquire an expired lease succeeds only in that locked
transaction and only when a matching authorisation exists. It receives a new epoch, then loads
the run state from `runs.run_data` and resumes from the latest checkpoint.

### Lease Heartbeat

The process actively working on a run refreshes the lease every **10 seconds** by re-issuing
`ACQUIRE_LEASE` with the same `owner_id` and epoch. If a process dies, its leases expire after
their 30-second TTL and become *eligible* for takeover — eligibility is not authorisation, and
the standby must still obtain an operator authorisation before it may acquire. Failure to renew
is a fencing signal, not permission to continue from cached ownership.

### Leader Election for Standby Promotion

There is no global leader election. Each run is owned independently:

- **Active process:** Continuously renews its lease on runs it is actively working on.
- **Standby process:** Polls `run_leases` every 5 seconds to *observe* leases that have expired
  on non-terminal runs. It records the observation and stops there: it must not acquire,
  dispatch, or resume the run until an operator authorisation exists for the observed epoch.
  Once the authorisation is present, it claims the lease under `FOR UPDATE`, receives a new
  epoch, and resumes only after loading the durable state.

The standby only takes over runs whose `runs.state` is non-terminal (not in `TERMINAL_STATES = {FAILED, ABORTED, PLAN_RCA_RESOLVED}`). Terminal runs are never leased.

The standby must never accelerate this path by deleting or rewriting the expired lease row.
A lease row is only ever changed by the epoch-incrementing acquisition transaction, or by the
audited manual-failover procedure described in the operations runbook.

### Run-Start Serialization

`start_issue` uses `SELECT FOR UPDATE` on the issue-number row to prevent two processes from simultaneously creating duplicate `RunRecord` entries:

```sql
-- Pessimistic lock on the issue number
BEGIN;
SELECT * FROM runs WHERE issue_number = $n FOR UPDATE;
-- If row exists: return existing run
-- If no row: INSERT new run, COMMIT
COMMIT;
```

---

## Split-Brain Mitigation and Residual Risk

Active/passive routing is an operational control, not proof that a former primary is dead. The
fencing contract protects durable mutations after a newer owner is granted; it complements,
but does not replace, failure diagnosis and GitHub idempotency.

| Scenario | Required mitigation | Residual risk / limit |
|---|---|---|
| Network partition isolates the primary from PostgreSQL but not necessarily from GitHub | The primary must fail readiness when it cannot reach PostgreSQL and must stop protected work when lease renewal fails. A standby takes over only after PostgreSQL reports expiry **and** an operator has authorised the takeover; all its protected writes use its new epoch. | A primary can still make an external GitHub request during the interval between losing DB access and observing renewal failure. Fencing cannot revoke that request; command/idempotency records and reconciliation detect/contain it. |
| Primary is paused or GC-stalled past TTL | PostgreSQL time expires the lease; the standby observes the expiry and stays quiescent until an operator authorisation is recorded. On authorised takeover the standby claims the lease under `FOR UPDATE` and increments epoch. On resumption, the old process's next protected write receives `StaleEpochError` and it stops. | A paused process may have an already-started external call; no automatic mechanism can prove it did not reach GitHub. The intent/outcome contract bounds the ambiguity but does not eliminate it. |
| Clock skew between application hosts | All expiry comparisons and epoch increments use PostgreSQL `NOW()` inside transactions. Hosts do not compare local wall clocks to decide takeover. Epoch validation, not local time, fences stale durable writes. | Clock skew can affect local scheduling/observability and cause delayed heartbeats, but cannot make a lower epoch valid. PostgreSQL availability and correct database time remain assumptions. |
| Manual force-release of a lease | Only an authorised runbook operator may force release after confirming the prior instance is terminated or isolated from both PostgreSQL and GitHub. The operation must be audited and must be followed by the normal epoch-incrementing acquisition path — never by a hand-written epoch rollback or a row deletion. | Force-releasing a still-live, externally connected primary intentionally creates the largest external side-effect risk. Manual failover is not safe automatic failover; do not use it merely to shorten TTL. |

**Honest boundary:** this ADR does not provide quorum-based membership, STONITH, consensus,
a transactional outbox, or exactly-once delivery to GitHub. It does not claim automatic
failover or active/active safety. Failover in the initial phase is an operator-authorised
procedure: the standby never takes over a lease on its own initiative. The deployment is safe
for durable state only to the extent that PostgreSQL remains the single writable authority and
the fencing checks are implemented on every protected path.

## External Side-Effect Intent and Outcome Reconciliation

Epoch fencing guarantees that a stale leader cannot commit durable database mutations after a newer lease epoch has been granted. However, epoch fencing **cannot revoke or abort an HTTP request to GitHub** that was already transmitted (or in flight) by a leader that subsequently lost its lease or was paused.


To handle external side effects safely without assuming distributed transactions across GitHub and PostgreSQL, OpsSwarm enforces a durable **intent/outcome reconciliation contract**.

### 1. The Intent-Outcome Contract

Before issuing any external write to GitHub (such as creating a comment, opening a pull request, or posting a remediation payload), the orchestrator executes the following transactional sequence:

1. **Lease & Epoch Validation:** In one transaction, take the `run_leases` row `FOR UPDATE` and
   verify that `owner_id` matches this process, that `epoch` matches the epoch this process
   holds, and that `expires_at > NOW()` (PostgreSQL server time).
2. **Intent Record Written Durably:** Still inside that transaction, insert a row into
   `external_side_effect_intents` with:
   - `intent_key` — the idempotency / command key, unique across the whole schema, derived
     from the GitHub comment id or the command identity so that the same logical action can
     never be recorded twice;
   - `epoch` — the lease epoch of the issuing leader;
   - `operation` and `target_ref` — what is being written and where;
   - `request_digest` — a digest of the outbound payload, so that a later reconciliation
     attempt can prove it is inspecting the same request;
   - `state = 'INTENDED'`.
   The transaction commits **before** the HTTP request is issued. A duplicate
   `intent_key` insert is rejected, which is what prevents two leaders from preparing the
   same side effect concurrently.
3. **Outbound HTTP Request:** Issue the request to GitHub, carrying the idempotency key where
   the GitHub API supports it, or performing a pre-check deduplication against existing
   comments/refs where it does not.
4. **Outcome Recording:** Immediately upon receiving the HTTP response, update the same
   `intent_key` row to `state = 'CONFIRMED'` (with the response detail in `outcome_detail`)
   or `state = 'FAILED'`. If the outcome cannot be determined — a timeout, a dropped
   connection, a process crash between the request and the response — the row is left at
   `INTENDED`, which is the durable signal of an ambiguous in-flight side effect.

A leader that loses its lease between steps 1 and 4 still has a durable intent row. It must
not update the outcome row with a stale epoch; the outcome update is a protected write and is
subject to the same `owner_id` / `epoch` validation.

### 2. Duplicate Prevention and What is Guaranteed vs. Detected

- **Guaranteed by the design:**
  - No database state corruption: all coordination writes are serialised by `FOR UPDATE`
    plus revision CAS.
  - First-wins command execution through `command_outcomes` and `seen_delivery_keys`
    (ADR-009-1, ADR-012).
  - A stale leader cannot record a new outcome or advance the run revision after a newer
    epoch has been granted; it receives `StaleEpochError` and commits nothing.
  - At most one intent row exists per idempotency/command key, so two leaders cannot
    concurrently prepare the same external side effect.
- **Detected and contained, not prevented:**
  - If a stale leader transmits an HTTP write to GitHub just as it is fenced, GitHub may
    receive that request. Fencing cannot undo it.
  - **Containment mechanism:** because the intent row is written before the call, the
    reconciliation path (`ReconciliationManager` on startup, and the standby's takeover
    recovery) can identify intents left in state `INTENDED` — that is, an intent with no
    recorded outcome.
  - Rather than blindly retrying, the recovering leader queries GitHub using the
    idempotency key (or the request digest / comment signature) to establish whether the
    side effect actually landed, and then records the reconciled outcome. This converts an
    unrecorded external write into a known one, preventing a duplicate creation.
  - **Limit:** if the reconciliation query itself cannot determine the outcome — for example
    the request was rejected by GitHub and no matching object exists but the request may
    still have been partially applied — the intent remains `INTENDED` and is surfaced to the
    operator as an ambiguous side effect requiring a human decision. OpsSwarm never resolves
    this case by guessing.

### 3. Failure-Injection Test Case: The Paused Leader Race

To verify this contract, the test suite includes a failure-injection scenario (`test_paused_leader_external_side_effect_reconciliation.py`):

```
Setup:
1. Primary instance P1 holds lease at epoch N for run R.
2. P1 initiates a GitHub comment action. It successfully validates its lease epoch N and writes the intent record to PostgreSQL.

Failure Injection:
3. P1 is forcibly paused (e.g., thread execution suspended or GC pause) immediately *after* writing the intent record and validating the lease, but *before* transmitting the HTTP write to GitHub.
4. Standby instance P2 observes lease expiry (TTL > 30s), obtains operator authorisation, acquires the lease at epoch N+1 under FOR UPDATE, reloads state, and initiates recovery.

Transition & Standby Takeover:
5. P2 encounters the unresolved intent record with no corresponding outcome. Instead of re-issuing a raw duplicate comment, P2 checks GitHub for existing comments matching the idempotency key. Finding none (or finding the prior one), P2 reconciles the outcome deterministically.
6. P1 unpauses and attempts to complete its HTTP write and update the database with epoch N.

Expected Result:
7. P1's database write is rejected with StaleEpochError (epoch N < N+1).
8. P1's external HTTP write (if transmitted) is detected as a duplicate or reconciled via idempotency keys; no duplicate comment is posted to GitHub.
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

## Readiness and Lifecycle Boundary

This ADR owns only the **HA coordination gate**. It does not define a second lifecycle,
drain state machine, or competing `/ready` endpoint contract. The canonical process-local
lifecycle owner is `opsswarm.runtime.get_readiness()` / `ReadinessManager`, as decided in
ADR-032 (task `t_644e3a9b`); `opsswarm.api` remains a wiring consumer.

The canonical contract remains: `/health` is liveness; `/ready` returns 200 only after startup
preflight and while the process is not draining, otherwise 503; drain rejects new mutable
admissions while accepted work settles. When HA is enabled, the canonical manager must compose
that local gate with an HA coordination dependency: PostgreSQL reachability plus verification
that the process may safely admit the relevant mutable work. A failed dependency produces the
canonical 503 outcome; this ADR does not prescribe a competing response shape or treat an empty
set of run leases as readiness on its own. GitHub HMAC validation remains independent of runtime
API authorisation.

---

## PostgreSQL Deployment and Failover Preconditions

Before any production HA claim, the deployment must use a concrete PostgreSQL topology. The
initial approved topology is **one managed PostgreSQL 14+ service with a separate primary and
hot standby replica in different failure domains**, exposed through the provider's writer
endpoint. An in-cluster PostgreSQL StatefulSet is excluded from the initial claim unless a later
ADR supplies equivalent replication, promotion, backup, and operational evidence.

- WAL archiving and point-in-time recovery must be enabled. The writer must use synchronous
  replication/commit acknowledgement to at least one designated synchronous standby for
  coordination writes; asynchronous replication is not sufficient for the stated failover
  guarantee. A planned database failover must promote the designated writer only after the old
  writer is fenced by the provider.
- Each OpsSwarm process uses a bounded connection pool with a distinct `application_name`,
  connection timeout, health check, and pool reset on database promotion. Connections surviving
  a promotion must be discarded and reacquired; the application must not reuse a transaction or
  cached lease result from the former writer.
- Transaction row locks (`SELECT ... FOR UPDATE`) and revision/epoch checks are the sole
  correctness mechanism. PostgreSQL advisory locks, if used for optional process coordination,
  are session-scoped acceleration only: they must never grant leadership, survive a pool reset,
  or replace the durable `run_leases` row and fencing checks.
- The database remains the only writer for the coordination schema. Direct `DELETE` or owner
  reassignment is prohibited outside the audited operator-authorised failover procedure; a
  takeover must be followed by normal epoch-incrementing acquisition, never by a hand-written
  epoch rollback or a lease-row deletion.

These requirements are contracts, not evidence that the deployment exists today. Until the
checklist below is complete, HA remains Proposed and `ha.enabled` is not an accepted production
claim.

---

## Evidence Required to Move to Accepted

ADR-031 remains **Proposed** until the Phase 1–6 implementation and the following evidence are
reviewed and retained with Issue #70. Phase 7 supplies the runbook and canary/rollback evidence,
but does not substitute for the implementation gates. The acceptance-test contract in this ADR
maps to the same cards; neither list is satisfied by documentation alone.

- [ ] **Phase 1 — persistence abstraction** (`t_854091a9`): `BaseStore` / `FileStore` split and
  a configuration-selected store implementation, with the filesystem path unchanged when
  `ha.enabled = false`.
- [ ] **Phase 2 — Postgres schema** (`t_676eff3d`): migration and rollback proof includes
  `run_leases.epoch`, the `epoch > 0` constraint, the `lease_takeover_authorisations` and
  `external_side_effect_intents` tables, and a durable monotonic takeover transaction. No
  time-dependent `CHECK (expires_at > NOW())` constraint is introduced.
- [ ] **Phase 3 — lease management** (`t_ac930e53`): heartbeat/takeover tests cover epoch
  increment, dynamic expiry evaluation using PostgreSQL server time, operator-authorised
  takeover, paused-leader fencing, and the four split-brain scenarios in this ADR.
- [ ] **Phase 4 — CAS enforcement** (`t_35dfc9b3`): command dispatch, comment/remediation
  writes, webhook-driven transitions, checkpoints, and evidence writes all use the protected
  epoch-validation contract.
- [ ] **Phase 5 — HA integration tests** (`t_5968c86a`): two-process tests demonstrate no
  stale-epoch durable write after takeover, deterministic command outcomes, evidence-chain
  continuity through takeover, and the paused-leader external side-effect reconciliation case.
- [ ] **Phase 6 — readiness/rate-limit integration** (`t_a3cff117`): tests show PostgreSQL
  loss fails the canonical readiness gate closed, composes with `ReadinessManager`/ADR-032
  without a second drain owner, and leaves `/health` as liveness.
- [ ] **Phase 7 — operations/runbook** (`t_8b5c83c8`): an approved runbook, rollback exercise,
  and a recorded canary procedure reference the chosen managed-Postgres topology and its
  synchronous-replication configuration, and describe the operator-authorised failover
  procedure rather than a lease-row deletion.
- [ ] **Deployment evidence:** topology/configuration record identifies writer and synchronous
  standby, WAL archive/PITR settings, `synchronous_commit` expectation, connection-pool limits,
  and advisory-lock policy; secrets are redacted.
- [ ] **Failover drill transcript:** dated staging (or production-approved) transcript identifies
  old/new database writer and app instances, injects a primary/app failure, records the
  operator authorisation, the promotion, connection-pool reset, lease epoch before/after, and
  bounded standby resumption.
- [ ] **Evidence-chain continuity report:** before/during/after drill export for at least one
  non-terminal run shows sequence/order, signatures, checkpoint resume point, no duplicate
  protected event, and successful independent SHA-256 chain verification.
- [ ] **Readiness fail-closed observation:** captured `/ready` 503 while PostgreSQL is
  unavailable or coordination validation fails, plus recovery to the canonical ready state after
  it is restored; it must also show no new mutable admission during local drain.

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
2. Observe that the primary's leases expire after the **30-second TTL** and that the standby
   records the expiry as an *eligible* lease. The standby does **not** acquire it.
3. Record an operator authorisation for the affected run, binding it to the observed epoch:

   ```bash
   psql $DATABASE -c "INSERT INTO lease_takeover_authorisations
                      (run_id, observed_epoch, approved_by, reason)
                      SELECT run_id, epoch, 'operator-identity', 'primary SIGTERM'
                      FROM run_leases
                      WHERE run_id = '<run-id>'"
   ```

4. The standby acquires the lease at epoch `N+1` under `FOR UPDATE`, resumes non-terminal runs
   from the latest checkpoint in the `checkpoints` table, and marks the authorisation consumed.
5. Verify via `SELECT owner_id, epoch, expires_at FROM run_leases` that the standby now owns
   the lease at the incremented epoch.

### Operator-Authorised Failover

Failover in the initial phase is always operator-authorised. The procedure is:

```bash
# 1. Confirm the previous owner is terminated or isolated from both PostgreSQL and GitHub.
# 2. Record the authorisation against the observed epoch (see "Simulating Primary Failure").
# 3. The standby performs the normal epoch-incrementing acquisition; it is never forced to
#    take the lease by deleting or rewriting the lease row.
```

**Do not** delete rows from `run_leases` to force a handover. A `DELETE` discards the epoch
history, breaks the fencing chain, and removes the durable evidence of which instance held
the run. A lease row changes only through the epoch-incrementing acquisition transaction or
through the audited authorisation path above.

### Checking HA Health

```bash
# Active leases per instance
psql $DATABASE -c "SELECT owner_id, count(*) FROM run_leases GROUP BY owner_id"

# Expired leases awaiting an operator authorisation (eligible, not yet authorised)
psql $DATABASE -c "SELECT run_id, owner_id, epoch FROM run_leases
                    WHERE expires_at <= NOW()"

# Outstanding takeover authorisations (observed_epoch -> consumed_epoch)
psql $DATABASE -c "SELECT run_id, observed_epoch, approved_by, consumed_epoch
                    FROM lease_takeover_authorisations
                    WHERE consumed_epoch IS NULL"

# Unresolved external side-effect intents (ambiguous in-flight writes)
psql $DATABASE -c "SELECT intent_key, run_id, epoch, operation, created_at
                    FROM external_side_effect_intents
                    WHERE state = 'INTENDED' ORDER BY created_at"

# Runs in progress
psql $DATABASE -c "SELECT run_id, state, updated_at FROM runs WHERE state NOT IN ('RESOLVED','FAILED','ABORTED','PLAN_RCA_RESOLVED') ORDER BY updated_at DESC"

# Evidence chain integrity
psql $DATABASE -c "SELECT run_id, count(*) FROM evidence GROUP BY run_id ORDER BY count DESC LIMIT 10"
```

---

## Explicit Acceptance-Test Contract & Kanban Ownership

**Status remains Proposed.** None of the migrations, schema tables, acceptance tests, or HA runtime wrappers described in this ADR exist in the repository today. They are future deliverables owned by specific in-flight Kanban cards as tracked below.

### Stated RPO and RTO Targets

These are **target** figures for the design, not measured values. No measurement exists today.

- **Recovery Point Objective (RPO):** `0` for all successfully committed coordination-database
  mutations, conditional on the deployment prerequisites in "Operator prerequisites for the
  PostgreSQL dependency" (WAL durability plus synchronous replication to at least one
  designated standby). Work that was uncommitted in a crashed leader's local memory is lost
  and is recovered by resuming from the latest persisted checkpoint (`checkpoints` table).
  The RPO does **not** cover an external GitHub side effect that was transmitted but whose
  outcome was never recorded; that case is detected and reconciled, not prevented (see
  "External Side-Effect Intent and Outcome Reconciliation").
- **Recovery Time Objective (RTO):** the design target is that a run is resumable **within one
  lease TTL (30 seconds) of the authorised takeover decision**. This is a *post-authorisation*
  objective only: the detection component is bounded by the lease TTL, but the **total**
  time to resume also includes the human operator-authorisation interval, which is not
  bounded by this ADR and is set by the deployment's operational practice. The ADR therefore
  claims no fixed end-to-end RTO number.

### Acceptance-Test Specifications and Kanban Ownership

The following tests are specified as formal acceptance criteria. Each test is owned by a specific in-flight Kanban task and must be implemented and verified within that task before this ADR can be considered for review or acceptance:

#### Test 1: Postgres-Backed Migration and Rollback
- **Specification:** Apply initial Alembic migration (`alembic upgrade head`) creating `runs`, `run_leases`, `lease_takeover_authorisations`, `external_side_effect_intents`, `evidence`, `rate_limit_buckets`, `checkpoints`, and `seen_delivery_keys`. Verify down migration (`alembic downgrade -1`) cleanly drops all HA tables without data loss to legacy filesystem fallback when `ha.enabled = false`. The migration must **not** introduce a time-dependent `CHECK (expires_at > NOW())` constraint on `run_leases`; see the schema section for the rationale.
- **Kanban Owner:** Task `t_676eff3d` (Phase 2 — Postgres Schema Definition) for the DDL and constraints, and Task `t_8b5c83c8` (Phase 7 — Ops Runbook + Alembic scaffolding) for the migration scripts and rollback exercise.

#### Test 2: Concurrent Leader Race and CAS Enforcement
- **Specification:** Two parallel processes attempt to claim the same run lease or update run state concurrently. Verify `SELECT FOR UPDATE` and revision CAS serialize execution, returning `StaleDataError` or `StaleEpochError` for loser processes with zero rows mutated.
- **Kanban Owner:** Task `t_35dfc9b3` (Phase 4 — State & CAS Enforcement) & Task `t_676eff3d` (Phase 2).

#### Test 3: Lease Expiry, Operator Authorisation, and Restart Behaviour
- **Specification:** Primary instance holds lease at epoch `N` and pauses or dies. Standby observes lease expiry but remains quiescent until an audited operator authorisation is recorded in `lease_takeover_authorisations`. Upon authorisation, standby acquires lease at epoch `N+1` under `FOR UPDATE`, reloads state from `runs.run_data` and latest checkpoint, and resumes work. Resumed primary with epoch `N` receives `StaleEpochError` on protected writes.
- **Kanban Owner:** Task `t_ac930e53` (Phase 3 — Lease Management & Takeover).

#### Test 4: External Side-Effect Intent-Outcome Reconciliation & Paused-Leader Race
- **Specification:** Primary writes intent record for an external GitHub write, then pauses before HTTP transmission. Standby takes over via authorised lease increment. Standby detects unresolved intent, reconciles via GitHub idempotency check rather than duplicate transmission. Paused primary resumes, attempts write with old epoch, and receives `StaleEpochError`.
- **Kanban Owner:** Task `t_5968c86a` (Phase 5 — HA Integration Tests).

#### Test 5: Readiness Fail-Closed on Coordination Loss
- **Specification:** When PostgreSQL becomes unreachable or lease validation fails, `/ready` responds with HTTP 503 while `/health` continues to return liveness (200). Restoring database connectivity recovers `/ready` to HTTP 200 without duplicating state.
- **Kanban Owner:** Task `t_a3cff117` (Phase 6 — Fail-Closed Readiness).

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

## Consequences

**Benefits:** PostgreSQL-issued epochs turn a lease into a durable fencing contract, so a former
leader cannot write protected OpsSwarm state after a successor is granted. The deployment and
acceptance-evidence requirements make the HA claim testable rather than aspirational.

**Costs and trade-offs:** every protected mutation now needs a transaction that validates the
lease epoch, and HA depends on an operationally mature managed PostgreSQL service with
synchronous replication. Availability is deliberately reduced during coordination uncertainty:
the canonical readiness gate fails closed rather than admitting mutable work without proof of
safe coordination.

**Non-goals:** this is not active/active processing, automatic failover, exactly-once external
side effects, or a replacement for the runtime-owned drain lifecycle.

---

## Alternatives Considered

|| Option | Description | Rejection Rationale |
|---|---|---|
| A — Postgres-backed coordination | This ADR — chosen | Best fit for the required cross-host transactional CAS and durable fencing; requires a managed PostgreSQL deployment dependency that does not exist in this repository today |
| B — Redis / BullMQ | Distributed queue + state | Not present in codebase; introduces new operational dependency |
| C — Leader election (Raft) | Embedded Raft consensus | Significant complexity; operational overhead; overkill for active/passive |
| D — Filesystem-only with flock | Keep JSON files, use NFS flock | NFS lock semantics vary across providers; not reliable for cross-host |
| E — Single-node only, no HA | Acknowledge limitation | Does not satisfy Issue #70 requirements |

---

## Implementation Phases

Implementation is divided into bounded phases. Each phase is a separate Kanban child task
(the card identifiers are the current owners of the acceptance-test contracts listed above):

1. **Phase 1 — Persistence abstraction** (`t_854091a9`): `BaseStore` abstraction with the
   filesystem implementation moved behind it; store selected by configuration.
2. **Phase 2 — Postgres schema definition** (`t_676eff3d`): DDL for `runs`, `run_leases`,
   `lease_takeover_authorisations`, `external_side_effect_intents`, `evidence`,
   `rate_limit_buckets`, `checkpoints`, and `seen_delivery_keys`; `epoch > 0` constraint;
   no time-dependent `CHECK` on `expires_at`.
3. **Phase 3 — Lease management and takeover** (`t_ac930e53`): `run_leases` accessors,
   instance ID generation, heartbeat thread, expiry evaluation via PostgreSQL server time,
   and takeover gated on an operator authorisation.
4. **Phase 4 — State and CAS enforcement** (`t_35dfc9b3`): `HaRunStore` with revision CAS and
   epoch validation on every protected write path; feature-flagged.
5. **Phase 5 — HA integration tests** (`t_5968c86a`): multi-process lease contention, failover
   during execution, atomic state transitions, and the paused-leader external side-effect
   reconciliation case.
6. **Phase 6 — Fail-closed readiness** (`t_a3cff117`): compose the HA coordination dependency
   with the canonical `ReadinessManager` / ADR-032 lifecycle gate; update integration tests
   without adding a lifecycle owner.
7. **Phase 7 — Ops runbook and canary rollout** (`t_8b5c83c8`): Alembic migration scaffolding
   and rollback exercise; runbook documentation covering the operator-authorised failover
   procedure; managed-Postgres topology evidence, failover drill, and gradual rollout with the
   `ha.enabled` feature flag.

Each phase is independently deployable and reversible via the feature flag `ha.enabled`.

---

## Compatibility and Migration

- **Backwards compatible:** All existing behavior is preserved when `ha.enabled = false` (default). No existing tests break.
- **Data migration:** JSONL evidence is read on first access and migrated lazily. Run records are migrated on first write.
- **Rollback:** Set `ha.enabled = false`. The `HaRunStore` / `HaEvidenceStore` wrappers fall back to filesystem implementations transparently.
- **Zero-downtime upgrade:** Add Postgres schema (migration 1) → deploy new code with `ha.enabled: false` → enable HA feature flag → zero-impact.
