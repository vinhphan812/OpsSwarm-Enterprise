# 0039. Bounded automatic rollback after a verifier regression

Date: 2026-10-16

## Status

Accepted

## Context

Issue #55 owns the recovery loop that follows a `REGRESSION` or `INCONCLUSIVE`
verifier verdict. The Verifier (ADR 0017) re-reads the Live Twin and reports
`VERIFIED` only when the post-commit state matches the transition the
`Decision` named. A mismatch is `REGRESSION`; an unreadable SKU or a missing
baseline is `INCONCLUSIVE`. The recovery path before this record was to fall
back to re-plan (ADR 0018) or to stop and wait for an operator. There was no
automatic path that reversed the change on the Live Twin.

Issue #85 forbids the agent from importing a model SDK. The decision to roll
back must not be made by the LLM. The recovery policy is deterministic code
that consumes the same artifacts the Verifier and the Guard already produce.
The decision to write to the Live Twin is still the guarded Executor's, on
the same atomic-commit boundary that the original commit used (ADR 0016).

Re-trying the original action until the verifier is happy was set aside: the
verifier reads the post-commit state, and the next commit would only push the
state further from the planned target. Halting the run on every `REGRESSION`
was set aside: the change already landed on the Live Twin and needs to be
reversed to keep the twin honest. Branching into a fresh planner without
undoing the change was set aside: the twin would carry a half-committed
mutation whose lineage is the failing decision.

Activation rule: this change implements and tests the recovery path, but it
stays off by default until the G06 submission gate (issue #53) has PASS
evidence. The flag is `RECOVERY_AUTO_ENABLED` (default `False`) and the
recovery entry-point on the Executor exposes it as an `enabled` parameter.
The review closes #55 once G06 is on record.

## Decision

`apps/api/retailtwin_api/agents/executor/recovery.py` defines the bounded
automatic rollback policy. The recovery is a two-step protocol:

1. `propose_recovery(decision, verification_report, audit_trail, *, baseline,
   current_versions, policy, attempt, enabled, now)` returns a typed
   `RecoveryProposal`. The proposal always carries the original
   `correlation_id` and `decision_id` so the audit chain stays linked.
2. `execute_recovery(proposal, *, auth_pipeline, executor, audit_trail, now)`
   returns a `RecoveryExecutionResult` with the terminal outcome.

### Policy dataclass

```python
@dataclass(frozen=True)
class RecoveryPolicy:
    max_attempts: int = 1
    inverse_only: bool = True
    linkage_required: bool = True
```

`max_attempts` caps the number of recovery proposals for one
`correlation_id`. The default is `1`. A second attempt returns
`BLOCKED_BUDGET_EXHAUSTED`. `inverse_only` keeps the recovery to mirrored
actions; turning it off is a planner-like behavior and must be re-ADR'd.
`linkage_required` refuses proposals whose decision is not in the recovery
audit sink under the same `correlation_id`.

### Outcomes

```python
class RecoveryOutcome(str, Enum):
    PROPOSED
    EXECUTED
    HUMAN_REVIEW_REQUIRED
    BLOCKED_NO_LINKAGE
    BLOCKED_BUDGET_EXHAUSTED
```

`VERIFIED` → `HUMAN_REVIEW_REQUIRED` (`reason_code="verified"`). An
already-confirmed decision has no automatic recovery; an operator reviews.

`REGRESSION` or `INCONCLUSIVE` with the policy enabled, the attempt budget
remaining, and linkage present → a `PROPOSED` proposal that names the
inverse action and the live versions it expects. The inverse action is:

- `replenish_shelf(N)` → `deplete_shelf(N)` (move `N` units back from shelf
  to backroom),
- `change_facings(F)` → `change_facings(F_baseline)` (restore the baseline
  facing count from the verifier snapshot),
- `move_product(A, B)` → `move_product(B, A)` (swap the slots back).

`enabled=False` keeps the proposal construction but records
`HUMAN_REVIEW_REQUIRED` (`reason_code="feature_disabled"`). `max_attempts`
exhausted is `BLOCKED_BUDGET_EXHAUSTED`. A missing linkage or an
unsupported shape (multi-SKU decisions, no inverse) is `HUMAN_REVIEW_REQUIRED`
or `BLOCKED_NO_LINKAGE` depending on the rule that fired.

### Execution gates

`execute_recovery` runs the synthetic inverse `Decision` through the same
`AuthPipeline` that authorizes an original commit:

- `ALLOW` on fresh reads (No-Stale-Commit, ADR 0015). The binding's
  `entity_versions` are compared against the proposal's
  `required_versions`; a mismatch is `stale_recovery` and is blocked.
- `DENY` or `HUMAN_REVIEW` returns `BLOCKED_NO_LINKAGE` with the guard
  reason code as the `reason_code`.
- The proposal's outcome is not `PROPOSED` (caller handed the function a
  non-actionable proposal) → the proposal's outcome is returned.

The `RecoveryExecutor` applies the inverse through the same Live Twin
boundary the guarded Executor uses. It refuses a stale read (the live version
must equal `required_versions`) and never writes half a change.

### Audit chain

The recovery events are written to `InMemoryRecoveryAudit` (process memory
stand-in). Each event carries `correlation_id`, `original_decision_id`,
`recovery_id` (`recovery:{decision_id}:r{attempt+1}`), `outcome`,
`reason_code`, `inverse_kind`, and `inverse_sku`. The original decision's
`correlation_id` is preserved, so the original execution trace and the
recovery execution trace are joined on the same id. Promoting this to the
BigQuery audit trail is a follow-up that does not change the protocol.

### Activation

`Settings.recovery_auto_enabled` defaults to `False`. `recover_from_regression`
in `agents/executor/executor.py` accepts an `enabled` flag and refuses to
execute a `PROPOSED` proposal when the flag is `False`. The wired entry-point
also accepts the `NoStaleCommit` instance and a constructed
`InverseExecutor` for the store; the entry-point then calls `propose_recovery`
followed by `execute_recovery`.

## Consequences

A `REGRESSION` or `INCONCLUSIVE` verifier verdict on a committed decision
can be reversed automatically without re-running the planner or calling a
model. The recovery uses the same DCG + freshness + atomic-commit
guarantees as the original action (ADRs 0014, 0015, 0016). The audit chain
shares the original `correlation_id` so the lineage from trigger → decision
→ commit → recovery is one trace.

The recovery flow is bounded: `max_attempts` defaults to `1` so a recovery
that itself regresses is not retried automatically. The feature flag keeps
the path opt-in until G06 evidence is on record. `linkage_required` is on
by default so a recovery cannot be issued against a decision that the
recovery sink never saw. The inverse proposal is shaped as a regular
`ActionUnion` so the existing DCG can evaluate it.

Limits and follow-ups:

- **Inverse ``replenish_shelf``.** The reverse of a replenishment moves the
  same quantity back from shelf to backroom. The synthetic decision that
  `execute_recovery` builds for the DCG reports the inverse as a forward
  `ReplenishShelf` of the same magnitude; the DCG checks the conservative
  precondition (the backroom has at least that many units) and the
  recovery executor applies ``deplete_shelf`` semantics. The day-0
  `ReplenishShelf` schema is unchanged.
- **Multi-SKU decisions.** A decision with more than one SKU has no single
  inverse. The proposal returns `HUMAN_REVIEW_REQUIRED` with
  `reason_code="no_inverse"`. Adding a multi-SKU inverse is a separate
  change.
- **Recovery audit to BigQuery.** `InMemoryRecoveryAudit` is the test
  stand-in. Promoting the events to `retailtwin.agent_action_audit` (or a
  new `retailtwin.recovery_audit` table) is a follow-up.
- **Activation.** The flag must stay `False` until G06 closes. The change
  does not promote any gate to PASS.
- **Web review.** The web does not render recovery events yet. The wired
  entry-point and the audit events are the API-side prerequisite; the UI
  follows issue #40.

- Pull request:
- Issue: #55
- Supersedes:
- Superseded by: