# ADR-009-1: GitHub Delivery/Comment Identity for Idempotency

**Status:** Proposed  
**Created:** 2026-09-22  
**Related:** Issue #9, PERSISTENCE_IDEMPOTENCY_TRIAGE-9.md

## Context

The current implementation in `opsswarm/api.py` processes every GitHub webhook and comment without deduplication. This
creates two distinct idempotency concerns:

1. **Webhook delivery idempotency** — GitHub may retry webhook deliveries. Without deduplication, the same event could
   trigger duplicate runs.
2. **Command idempotency** — A user might issue the same `/opsswarm approve` command multiple times (e.g., due to UI
   refresh or network retry).

## Policy Decision

**Adopt Option A:** Use GitHub-managed IDs as idempotency keys.

- For webhooks: Use `X-GitHub-Delivery` header (UUID) for event deduplication
- For commands: Use comment ID from the GitHub API payload

### Source Code Anchors

| Concern          | File                               | Current State                                                    |
|------------------|------------------------------------|------------------------------------------------------------------|
| Webhook ingress  | `opsswarm/api.py:35-48`            | No deduplication; every valid webhook processes                  |
| Comment handling | `opsswarm/orchestrator.py:121-156` | No command deduplication; each comment triggers `handle_comment` |
| RunRecord        | `opsswarm/models.py:137-156`       | No idempotency_key field                                         |

## Alternatives Considered

| Option | Description                 | Rejection Rationale                                                    |
|--------|-----------------------------|------------------------------------------------------------------------|
| B      | Application-generated UUIDs | Adds complexity; GitHub IDs are already available and tamper-resistant |
| C      | Content hashing             | Fragile; same intent with different wording would be treated as new    |

## Implementation Dependencies

1. **Add idempotency_key to RunRecord** (`models.py`)
   ```python
   idempotency_keys: set[str] = Field(default_factory=set)  # GitHub delivery/comment IDs
   ```

2. **Webhook deduplication** (`api.py`)
    - Extract `X-GitHub-Delivery` header
    - Check against stored idempotency keys before processing
    - Store key on first process

3. **Command deduplication** (`orchestrator.py`)
    - Extract comment ID from GitHub payload
    - Check against idempotency keys before executing commands
    - Store key on first execution

## Compatibility & Migration

- **Backwards compatible:** Adding new fields to RunRecord is non-breaking
- **Migration:** No data migration required; new keys populate on first use
- **Rollback:** Remove idempotency_key field to revert; degraded behavior (possible duplicates)

## Security Impact

- **Low risk:** Idempotency keys are GitHub-managed UUIDs, not user-controlled
- **Denial of service:** Without idempotency, an attacker could spam webhooks to cause duplicate processing
- **Audit trail:** Idempotency keys provide natural deduplication for audit logs

## Source Drift Mitigation

- ADR links to specific source anchors in `api.py`, `orchestrator.py`, `models.py`
- Implementation task T6 (Add idempotency fields to RunRecord) must verify against these anchors
- Code review must confirm idempotency logic added at each anchor point
