# 0015. Recheck live versions before every commit

Date: 2026-10-13

## Status

Accepted

## Context

Issue #17 requires that a decision valid at Live Twin version N can never cross the live boundary at N+1 without revalidation. The test scenario is D1 at N, then the relevant state moves to N+1: the commit is blocked, Live is unchanged, and an audit event says why. ADR 0014 gives a deterministic guard. Its `ALLOW` result carries the live versions it read and a context hash over the decision id, store, versions and actions. #85 forbids binding staleness to provider metadata.

Trusting the first `ALLOW` until expiry was set aside: state can move between planning and commit. Comparing the store-level `context_version` was set aside for the reason ADR 0014 gives. Locking the Live Twin for the life of a decision was set aside: Firestore has no long-held lock, and an operator change must not wait on a plan.

## Decision

`NoStaleCommit` in `apps/api/retailtwin_api/guard/decision_context_guard/no_stale_commit.py` wraps the guard with an injected `GuardAuditSink` and clock.

`authorize(decision)` runs the guard on fresh Live Twin reads. It returns a `CommitBinding` only on `ALLOW`. The binding carries:

- `decision_id`
- `store_id`
- `context_hash`
- `entity_versions`: integer live version per touched SKU
- `expiry`: when the oldest context ages out

Any other verdict returns no binding, so no commit authorization can be issued from it.

`recheck(decision, binding)` runs the guard again immediately before the commit:

| Situation | Result |
| --- | --- |
| A touched SKU moved | `REFRESH_REQUIRED VERSION_STALE` |
| The context aged out | `REFRESH_REQUIRED CONTEXT_EXPIRED` |
| An `ALLOW` after `binding.expiry` on the wrapper clock | `REFRESH_REQUIRED CONTEXT_EXPIRED`, recorded as a `binding` check |
| An `ALLOW` whose hash differs from the binding | `DENY BINDING_MISMATCH`, recorded as a `binding` check |

The binding's expiry is authoritative. The context hash does not cover the decision's timestamps, so a caller that copies `context_timestamp` and evidence `freshness` forward cannot extend an authorization past the expiry it was given.

On `ALLOW` the live versions equal the evidence, so a different hash means a different decision id, store or action list.

Each call records one `GuardAuditEvent`. The event fields are:

- `stage` (`authorize` or `commit`)
- `decision_id`
- `correlation_id` from the first evidence bundle
- `store_id`
- `verdict`
- `reason_code`
- `failed_gate`
- `context_hash`
- live `entity_versions`
- `at`

The event carries no model text and no provider identifiers. `InMemoryGuardAudit` is the process-memory sink. It stores and returns deep copies, so a caller cannot rewrite recorded history.

The Executor (#18) must call `recheck` right before writing. It must also write each document with `expected_version` set to the binding's `entity_versions`, so a change that lands between the recheck and the write is refused by the Live Twin's optimistic concurrency.

## Consequences

The G04 scenario runs against the real guard in `tests/e2e/test_stale_context.py` and in `apps/api/tests/test_no_stale_commit.py`. A change to a SKU that the decision does not touch does not block it.

Refreshing evidence and re-planning after `REFRESH_REQUIRED` is #20. The audit is process memory until the BigQuery trail (#35). The race between the recheck and the write is closed only once the Executor uses the binding's versions (#18).

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/149
- Issue: #17
- Supersedes:
- Superseded by:
