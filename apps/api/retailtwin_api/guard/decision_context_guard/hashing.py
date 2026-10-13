"""Canonical action and context hashes.

The same action always serializes to the same bytes, so a commit
authorization can name exactly the actions it allows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from retailtwin_api.contracts import ActionUnion, ChangeFacings, MoveProduct, ReplenishShelf
from retailtwin_api.guard.decision_context_guard.policy import (
    CHANGE_FACINGS,
    MOVE_PRODUCT,
    REPLENISH_SHELF,
)


def action_type(action: ActionUnion) -> str:
    if isinstance(action, MoveProduct):
        return MOVE_PRODUCT
    if isinstance(action, ChangeFacings):
        return CHANGE_FACINGS
    if isinstance(action, ReplenishShelf):
        return REPLENISH_SHELF
    raise TypeError(f"Unknown action {type(action).__name__}.")


def canonical_action(action: ActionUnion) -> dict[str, Any]:
    return {"type": action_type(action), **action.model_dump(mode="json")}


def action_hash(action: ActionUnion) -> str:
    return _sha256(canonical_action(action))


def context_hash(
    decision_id: str,
    store_id: str,
    entity_versions: Mapping[str, str],
    actions: Sequence[ActionUnion],
) -> str:
    """Hash of what a commit depends on: the decision, the live versions it read, its actions."""

    return _sha256(
        {
            "decision_id": decision_id,
            "store_id": store_id,
            "entity_versions": dict(sorted(entity_versions.items())),
            "actions": [canonical_action(action) for action in actions],
        }
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
