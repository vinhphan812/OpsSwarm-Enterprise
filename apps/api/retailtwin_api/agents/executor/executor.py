"""Guarded Executor: the only code that writes an agent decision to the Live Twin.

``commit(decision, token)`` applies the decision only when every check passes, in
this order:

1. the signed authorization is present, untampered, unexpired, for exactly these
   actions, and not used before (``CommitAuthorizer.redeem``);
2. No-Stale-Commit rechecks the guard on fresh reads (``NoStaleCommit.recheck``);
3. each touched SKU is still at the version the authorization names;
4. the Live Twin accepts one atomic ``commit_inventory`` of every touched SKU, each
   conditional on that version, together with the store version step.

The commit is all-or-nothing at the repository boundary: Firestore applies one
``:commit`` entirely or not at all, and the in-memory twin does the same under its
lock. A conflict or failure writes nothing. A successful commit advances each
touched SKU by one version and the store ``v<N>`` by one.

The Executor never learns which model produced the decision.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

from retailtwin_api.contracts import (
    ChangeFacings,
    DCGVerdict,
    DCGVerdictResult,
    Decision,
    ExecutorResult,
    ReplenishShelf,
)
from retailtwin_api.firestore_twin import InventoryDocument, LiveTwinRepository, TwinConflict
from retailtwin_api.guard.decision_context_guard import (
    VERSION_STALE,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.authorization import (
    AuthorizationError,
    CommitAuthorizer,
    SignedAuthorization,
)

log = logging.getLogger(__name__)

COMMITTED = "COMMITTED"
EXECUTION_FAILED = "EXECUTION_FAILED"

Status = Literal["committed", "refused", "failed"]


class CommitOutcome(BaseModel):
    """What the Executor did with one decision."""

    model_config = ConfigDict(frozen=True)

    status: Status
    reason_code: str
    decision_id: str
    results: list[ExecutorResult]
    entity_versions: dict[str, int]
    store_version: str | None
    guard: DCGVerdictResult | None = None

    @property
    def committed(self) -> bool:
        return self.status == "committed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GuardedExecutor:
    def __init__(
        self,
        twin: LiveTwinRepository,
        authorizer: CommitAuthorizer,
        gate: NoStaleCommit,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._twin = twin
        self._authorizer = authorizer
        self._gate = gate
        self._clock = clock

    def commit(self, decision: Decision, token: SignedAuthorization | None) -> CommitOutcome:
        try:
            binding = self._authorizer.redeem(decision, token)
        except AuthorizationError as refused:
            log.warning("executor refused decision_id=%s reason=%s", decision.decision_id, refused.code)
            return self._outcome(decision, "refused", refused.code)

        guard = self._gate.recheck(decision, binding)
        if guard.verdict is not DCGVerdict.ALLOW:
            log.warning("executor refused decision_id=%s reason=%s", decision.decision_id, guard.reason_code)
            return self._outcome(decision, "refused", guard.reason_code, guard=guard)

        try:
            originals = {sku: self._read(binding.store_id, sku) for sku in binding.entity_versions}
        except Exception:
            log.error("executor live read failed decision_id=%s", decision.decision_id)
            return self._outcome(decision, "failed", EXECUTION_FAILED, guard=guard)
        if any(originals[sku].version != version for sku, version in binding.entity_versions.items()):
            return self._outcome(decision, "refused", VERSION_STALE, guard=guard)

        planned = _apply(decision, originals, self._clock())
        try:
            store = self._twin.commit_inventory(
                binding.store_id, [(target, originals[sku].version) for sku, target in planned.items()]
            )
        except TwinConflict:
            log.warning("executor write conflict decision_id=%s", decision.decision_id)
            return self._outcome(decision, "refused", VERSION_STALE, guard=guard)
        except Exception:
            log.error("executor write failed decision_id=%s", decision.decision_id)
            return self._outcome(decision, "failed", EXECUTION_FAILED, guard=guard)

        log.info(
            "executor committed decision_id=%s skus=%s store_version=%s",
            decision.decision_id,
            ",".join(planned),
            store.version,
        )
        return CommitOutcome(
            status="committed",
            reason_code=COMMITTED,
            decision_id=decision.decision_id,
            results=[
                ExecutorResult(action_id=_action_id(decision, i), status="applied", error=None)
                for i in range(len(decision.proposed_actions))
            ],
            entity_versions={sku: target.version for sku, target in planned.items()},
            store_version=store.version,
            guard=guard,
        )

    def _read(self, store_id: str, sku: str) -> InventoryDocument:
        doc = self._twin.get_inventory(store_id, sku)
        if doc is None:
            raise LookupError(sku)
        return doc

    def _outcome(
        self,
        decision: Decision,
        status: Status,
        reason_code: str,
        guard: DCGVerdictResult | None = None,
    ) -> CommitOutcome:
        return CommitOutcome(
            status=status,
            reason_code=reason_code,
            decision_id=decision.decision_id,
            results=[
                ExecutorResult(action_id=_action_id(decision, i), status="not_applied", error=reason_code)
                for i in range(len(decision.proposed_actions))
            ],
            entity_versions={},
            store_version=None,
            guard=guard,
        )


def _action_id(decision: Decision, index: int) -> str:
    return f"{decision.decision_id}:{index}"


def _apply(
    decision: Decision, originals: dict[str, InventoryDocument], now: datetime
) -> dict[str, InventoryDocument]:
    """Each touched SKU after all of its actions, one version ahead. The guard proved they fit."""

    state = {sku: doc.model_copy() for sku, doc in originals.items()}
    for action in decision.proposed_actions:
        doc = state[action.sku]
        if isinstance(action, ReplenishShelf):
            doc.backroom_quantity -= action.quantity
            doc.shelf_quantity += action.quantity
        elif isinstance(action, ChangeFacings):
            doc.facings = action.facings
        else:
            # MoveProduct. Slot ids are unique across shelves; the layout, not the twin,
            # maps a slot to its shelf.
            doc.slot_id = action.to_slot
    planned: dict[str, InventoryDocument] = {}
    for action in decision.proposed_actions:
        if action.sku not in planned:
            doc = state[action.sku]
            planned[action.sku] = doc.model_copy(update={"version": originals[action.sku].version + 1, "updated_at": now})
    return planned
