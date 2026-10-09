# Issue #70: HA Coordination Implementation Plan

This implementation plan outlines the phased transition to support High Availability (HA) in OpsSwarm enterprise deployments via a PostgreSQL state backend.

## Roadmap

| Phase | Title | Objective |
|---|---|---|
| 1 | Persistence Abstraction | Introduce `RunStore` interface allowing pluggable File/Postgres backends. |
| 2 | Postgres Schema Defin | Define SQL schema for `leases`, `run_records`, and `state_transitions`. |
| 3 | Lease Management | Implement distributed lock acquisition (lease ownership/expiry/takeover). |
| 4 | State & CAS Enforcem | Migrate state transitions to atomic Postgres CAS operations. |
| 5 | HA Integration Tests | Verify multi-process concurrency, crash/rollback, and failover behavior. |

---

## Detailed Tasks

### Phase 1: Persistence Abstraction (dev-android, parent: none)
- Refactor `opsswarm/store.py` to define a `BaseStore` abstract base class.
- Move existing filesystem-based logic into `FileStore(BaseStore)`.
- Update `Orchestrator` to accept a configured store implementation via `config.yaml`.
- Ensure backward compatibility with existing file-based runs.

### Phase 2: Postgres Schema Definition (dev-architect, parent: Phase 1)
- Write DDL for `run_records` and `leases` tables.
- Add migration scripts (using project's existing migration pattern if any).
- Validate schema constraints (foreign keys, NOT NULL, CHECK).

### Phase 3: Lease Management (dev-android, parent: Phase 2)
- Implement `PostgresStore.acquire_lease(run_id, owner_id, duration)`.
- Implement `PostgresStore.release_lease(run_id, owner_id)`.
- Ensure lease takeover logic (graceful expiry check).

### Phase 4: State & CAS Enforcement (dev-backend, parent: Phase 3)
- Implement `PostgresStore.update_run_state(run_id, new_state, expected_version)`.
- Ensure CAS logic holds to prevent race conditions across parallel orchestrators.
- Update `Orchestrator` workflow to use these store methods for state updates.

### Phase 5: HA Integration Tests (dev-qa, parent: Phase 4)
- Create new integration tests in `tests/integration/ha/`:
    - `test_multiprocess_lease_contention.py`
    - `test_failover_during_execution.py`
    - `test_atomic_state_transitions.py`
- Verify system can survive unexpected process termination during workflow transitions.

---

## Technical Constraints & Guardrails

- **No BullMQ/Redis:** Do not introduce BullMQ or Redis as per requirement. Stay committed to PostgreSQL as the single source of truth for coordination.
- **Fail-Closed:** If the database becomes unreachable, the orchestrator must reject new transitions, not fallback to an inconsistent state.
- **Transactional Integrity:** All state-modifying operations (state transition, lease check) must be contained within a single Postgres transaction or CAS operation.
