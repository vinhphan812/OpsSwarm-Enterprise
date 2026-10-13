"""Decision Context Guard: deterministic gates before any live commit.

The guard reads the Live Twin, never writes it, and never calls a model. Gates
run in a fixed order and the first failure decides the verdict:

1. integrity      DENY              the decision is well formed: one store, one
                                    correlation id, timezone-aware timestamps not in the future
2. evidence       DENY              every evidence bundle is sufficient and consistent
3. context        REFRESH_REQUIRED  each SKU an action touches is still at the version the
                                    evidence read (DENY when that version is missing)
4. freshness      REFRESH_REQUIRED  the oldest context is within the policy TTL
5. feasibility    DENY              the actions fit the live shelf and backroom
6. policy         HUMAN_REVIEW      the actions are inside the autonomous limits
                                    (DENY for an action type the policy does not allow)

Any Live Twin read failure is DENY. Only ALLOW lets a commit authorization be
issued.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from retailtwin_api.contracts import (
    ActionUnion,
    ChangeFacings,
    DCGVerdict,
    DCGVerdictResult,
    Decision,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.firestore_twin import InventoryDocument
from retailtwin_api.guard.decision_context_guard.hashing import action_type, context_hash
from retailtwin_api.guard.decision_context_guard.policy import GuardPolicy

log = logging.getLogger(__name__)

ALLOWED = "ALLOWED"
INVALID_DECISION = "INVALID_DECISION"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
MISSING_CONTEXT_VERSION = "MISSING_CONTEXT_VERSION"
UNKNOWN_ENTITY = "UNKNOWN_ENTITY"
VERSION_STALE = "VERSION_STALE"
CONTEXT_EXPIRED = "CONTEXT_EXPIRED"
INFEASIBLE_ACTION = "INFEASIBLE_ACTION"
ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
POLICY_THRESHOLD = "POLICY_THRESHOLD"
TWIN_UNAVAILABLE = "TWIN_UNAVAILABLE"

GATES: tuple[str, ...] = ("integrity", "evidence", "context", "freshness", "feasibility", "policy")

Clock = Callable[[], datetime]


class LiveTwinReader(Protocol):
    """The Live Twin reads the guard needs. ``LiveTwinRepository`` satisfies it."""

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None: ...

    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]: ...


@dataclass(frozen=True)
class _Failure:
    verdict: DCGVerdict
    reason_code: str
    detail: str


@dataclass
class _Context:
    """What the gates learn about one decision as they run."""

    store_id: str = ""
    correlation_id: str = ""
    claimed: dict[str, str] = field(default_factory=dict)
    live: dict[str, InventoryDocument] = field(default_factory=dict)
    oldest: datetime | None = None

    def live_versions(self) -> dict[str, str]:
        return {sku: str(doc.version) for sku, doc in self.live.items()}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DecisionContextGuard:
    """Evaluate a Decision against current Live Twin state."""

    def __init__(
        self,
        twin: LiveTwinReader,
        policy: GuardPolicy | None = None,
        clock: Clock = _utcnow,
    ) -> None:
        self._twin = twin
        self._policy = policy or GuardPolicy()
        self._clock = clock

    @property
    def policy(self) -> GuardPolicy:
        return self._policy

    def evaluate(self, decision: Decision) -> DCGVerdictResult:
        now = self._clock()
        ctx = _Context()
        checks: list[dict[str, Any]] = []
        gates: tuple[tuple[str, Callable[[], _Failure | None]], ...] = (
            ("integrity", lambda: self._integrity(decision, ctx, now)),
            ("evidence", lambda: self._evidence(decision, ctx)),
            ("context", lambda: self._context(decision, ctx)),
            ("freshness", lambda: self._freshness(ctx, now)),
            ("feasibility", lambda: self._feasibility(decision, ctx)),
            ("policy", lambda: self._authorization(decision)),
        )
        for gate, check in gates:
            failure = check()
            checks.append({"gate": gate, "passed": failure is None, "detail": failure.detail if failure else ""})
            if failure is not None:
                log.info(
                    "dcg verdict decision_id=%s correlation_id=%s verdict=%s reason=%s gate=%s",
                    decision.decision_id,
                    ctx.correlation_id,
                    failure.verdict.value,
                    failure.reason_code,
                    gate,
                )
                return self._result(decision, ctx, failure.verdict, failure.reason_code, gate, checks, now)
        log.info(
            "dcg verdict decision_id=%s correlation_id=%s verdict=ALLOW",
            decision.decision_id,
            ctx.correlation_id,
        )
        assert ctx.oldest is not None
        return self._result(
            decision, ctx, DCGVerdict.ALLOW, ALLOWED, None, checks, ctx.oldest + self._policy.freshness
        )

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    def _integrity(self, decision: Decision, ctx: _Context, now: datetime) -> _Failure | None:
        for name in ("decision_id", "agent_id", "context_version"):
            if not getattr(decision, name).strip():
                return _deny(INVALID_DECISION, f"{name} is empty.")
        if not decision.proposed_actions:
            return _deny(INVALID_DECISION, "The decision proposes no action.")
        if not decision.evidence:
            return _deny(INVALID_DECISION, "The decision carries no evidence.")
        stores = {bundle.store_id for bundle in decision.evidence}
        if len(stores) != 1:
            return _deny(INVALID_DECISION, "Evidence comes from more than one store.")
        ctx.store_id = stores.pop()
        correlations = {bundle.correlation_id.strip() for bundle in decision.evidence}
        if len(correlations) != 1 or "" in correlations:
            return _deny(INVALID_DECISION, "Evidence must carry exactly one non-blank correlation id.")
        ctx.correlation_id = correlations.pop()
        seen: set[tuple[str, str]] = set()
        for action in decision.proposed_actions:
            key = (action_type(action), action.sku)
            if key in seen:
                return _deny(INVALID_DECISION, f"{key[0]} is proposed twice for {action.sku}.")
            seen.add(key)
        # Context age comes from the decision and each bundle's freshness; collection
        # times are checked for shape and clock too, but do not extend the expiry.
        stamps = [decision.context_timestamp, *(bundle.freshness for bundle in decision.evidence)]
        checked = [*stamps, *(bundle.collected_at for bundle in decision.evidence)]
        if any(stamp.tzinfo is None for stamp in checked):
            return _deny(INVALID_DECISION, "Context timestamps must be timezone-aware.")
        if any(stamp > now + self._policy.clock_skew for stamp in checked):
            return _deny(INVALID_DECISION, "A context timestamp is in the future.")
        ctx.oldest = min(stamps)
        return None

    def _evidence(self, decision: Decision, ctx: _Context) -> _Failure | None:
        for bundle in decision.evidence:
            if not bundle.is_sufficient:
                return _deny(INSUFFICIENT_EVIDENCE, f"Evidence bundle {bundle.bundle_id} is insufficient.")
            for sku, version in bundle.entity_versions.items():
                known = ctx.claimed.setdefault(sku, version)
                if known != version:
                    return _deny(CONFLICTING_EVIDENCE, f"Evidence disagrees on the version of {sku}.")
        return None

    def _context(self, decision: Decision, ctx: _Context) -> _Failure | None:
        for sku in _touched_skus(decision.proposed_actions):
            if sku not in ctx.claimed:
                return _deny(MISSING_CONTEXT_VERSION, f"No evidence version for {sku}.")
            try:
                doc = self._twin.get_inventory(ctx.store_id, sku)
            except Exception:
                log.error(
                    "dcg live read failed decision_id=%s correlation_id=%s sku=%s",
                    decision.decision_id,
                    ctx.correlation_id,
                    sku,
                )
                return _deny(TWIN_UNAVAILABLE, "The Live Twin could not be read.")
            if doc is None:
                return _deny(UNKNOWN_ENTITY, f"{sku} is not in store {ctx.store_id}.")
            ctx.live[sku] = doc
        for sku, doc in ctx.live.items():
            if ctx.claimed[sku] != str(doc.version):
                return _Failure(
                    DCGVerdict.REFRESH_REQUIRED,
                    VERSION_STALE,
                    f"{sku} is at version {doc.version}; the decision read {ctx.claimed[sku]}.",
                )
        return None

    def _freshness(self, ctx: _Context, now: datetime) -> _Failure | None:
        assert ctx.oldest is not None
        age = now - ctx.oldest
        if age > self._policy.freshness:
            return _Failure(
                DCGVerdict.REFRESH_REQUIRED,
                CONTEXT_EXPIRED,
                f"Context is {int(age.total_seconds())}s old; the limit is "
                f"{int(self._policy.freshness.total_seconds())}s.",
            )
        return None

    def _feasibility(self, decision: Decision, ctx: _Context) -> _Failure | None:
        state = {sku: doc.model_copy() for sku, doc in ctx.live.items()}
        occupants: dict[str, str] | None = None
        for action in decision.proposed_actions:
            doc = state[action.sku]
            if isinstance(action, ReplenishShelf):
                if action.quantity > doc.backroom_quantity:
                    return _deny(
                        INFEASIBLE_ACTION,
                        f"{action.sku} has {doc.backroom_quantity} in the backroom; {action.quantity} requested.",
                    )
                doc.backroom_quantity -= action.quantity
                doc.shelf_quantity += action.quantity
            elif isinstance(action, ChangeFacings):
                if action.facings > self._policy.max_facings:
                    return _deny(
                        INFEASIBLE_ACTION,
                        f"{action.facings} facings exceed the slot limit of {self._policy.max_facings}.",
                    )
                doc.facings = action.facings
            elif isinstance(action, MoveProduct):
                if action.from_slot != doc.slot_id:
                    return _deny(INFEASIBLE_ACTION, f"{action.sku} is in {doc.slot_id}, not {action.from_slot}.")
                if action.to_slot == action.from_slot:
                    return _deny(INFEASIBLE_ACTION, f"{action.sku} already is in {action.to_slot}.")
                if occupants is None:
                    try:
                        occupants = {item.slot_id: item.sku for item in self._twin.list_inventory(ctx.store_id)}
                    except Exception:
                        log.error(
                            "dcg live list failed decision_id=%s correlation_id=%s",
                            decision.decision_id,
                            ctx.correlation_id,
                        )
                        return _deny(TWIN_UNAVAILABLE, "The Live Twin could not be read.")
                    occupants.update({item.slot_id: sku for sku, item in state.items()})
                occupant = occupants.get(action.to_slot)
                if occupant is not None and occupant != action.sku:
                    return _deny(INFEASIBLE_ACTION, f"{action.to_slot} is occupied by {occupant}.")
                occupants.pop(action.from_slot, None)
                occupants[action.to_slot] = action.sku
                doc.slot_id = action.to_slot
        return None

    def _authorization(self, decision: Decision) -> _Failure | None:
        policy = self._policy
        for action in decision.proposed_actions:
            kind = action_type(action)
            if kind not in policy.allowed_actions:
                return _deny(ACTION_NOT_ALLOWED, f"{kind} is not allowed in autonomous mode.")
        if len(decision.proposed_actions) > policy.max_actions:
            return _review(f"{len(decision.proposed_actions)} actions exceed the limit of {policy.max_actions}.")
        for action in decision.proposed_actions:
            if isinstance(action, ReplenishShelf) and action.quantity > policy.max_replenish_units:
                return _review(
                    f"Replenishing {action.quantity} units of {action.sku} exceeds the limit of "
                    f"{policy.max_replenish_units}."
                )
        return None

    # ------------------------------------------------------------------

    def _result(
        self,
        decision: Decision,
        ctx: _Context,
        verdict: DCGVerdict,
        reason_code: str,
        failed_gate: str | None,
        checks: list[dict[str, Any]],
        expiry: datetime,
    ) -> DCGVerdictResult:
        versions = ctx.live_versions()
        return DCGVerdictResult(
            verdict=verdict,
            reason_code=reason_code,
            context_version=decision.context_version,
            context_hash=context_hash(decision.decision_id, ctx.store_id, versions, decision.proposed_actions),
            expiry=expiry,
            policy_result={
                "failed_gate": failed_gate,
                "checks": checks,
                "store_id": ctx.store_id,
                "correlation_id": ctx.correlation_id,
                "entity_versions": versions,
            },
        )


def _deny(reason_code: str, detail: str) -> _Failure:
    return _Failure(DCGVerdict.DENY, reason_code, detail)


def _review(detail: str) -> _Failure:
    return _Failure(DCGVerdict.HUMAN_REVIEW, POLICY_THRESHOLD, detail)


def _touched_skus(actions: Sequence[ActionUnion]) -> list[str]:
    return list(dict.fromkeys(action.sku for action in actions))
