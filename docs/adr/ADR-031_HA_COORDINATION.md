# ADR-031: HA Coordination and PostgreSQL State Backend

**Status:** Proposed
**Created:** 2026-10-09
**Related:** Issue #70

---

## Context

OpsSwarm is currently constrained to single-node deployments using a file-based run store. As usage scales, this creates:
1. **Single Point of Failure:** The local disk is a SPOF for execution state.
2. **Horizontal Scaling Limits:** No shared state across multiple orchestrator processes.
3. **Coordination Gaps:** No native support for distributed locking, lease management, or Compare-And-Swap (CAS) operations needed for High Availability (HA).

To enable multi-instance HA deployments, we need a shared, durable, and ACID-compliant state backend. PostgreSQL is the established infrastructure standard for this project.

---

## Decision

**Adopt PostgreSQL as the primary shared state backend for run orchestration, leases, and state synchronization.**

1. **Backend Abstraction:** Introduce a `RunStore` interface that supports both `FileStore` (legacy/single-node) and `PostgresStore` (HA) backends.
2. **Schema:** Use a PostgreSQL schema for `run_records`, `leases`, and `state_transitions` to ensure consistency.
3. **Lease Management:** Leverage Postgres `SELECT ... FOR UPDATE` (or advisory locks) for distributed lease acquisition to ensure only one instance coordinates a given run.
4. **CAS Transitions:** Use atomically conditional updates (CAS) for run state transitions to prevent race conditions across orchestrator instances.

---

## Technical Approach

### Postgres Schema

```sql
CREATE TABLE leases (
    run_id VARCHAR(255) PRIMARY KEY,
    owner_id VARCHAR(255),
    expires_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE run_records (
    run_id VARCHAR(255) PRIMARY KEY,
    state VARCHAR(50),
    data JSONB, -- Serialized RunRecord
    version INT DEFAULT 0
);
```

### State Transitions (CAS)
Condition: `UPDATE run_records SET state = 'NEW_STATE', version = version + 1 WHERE run_id = :id AND state = :current_state AND version = :current_version`

---

## Consequences

**Positive:**
- Horizontal scaling supported via shared Postgres instance.
- ACID guarantees for all state transitions.
- Distributed locking via `leases` table provides HA coordination.

**Negative:**
- Increased infrastructure complexity (requires managed/self-hosted Postgres).
- Overhead of network communication for state synchronization.

**Mitigation:**
- Retain `FileStore` for low-footprint single-node dev/test environments.
- Implement efficient connection pooling in `PostgresStore`.

---

## Implementation Plan

See `docs/guides/HA_COORDINATION_PLAN.md` for the phased delivery breakdown.
