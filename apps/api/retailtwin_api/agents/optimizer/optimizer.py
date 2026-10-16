"""Deterministic constrained retail candidate optimizer (issue #54).

The optimizer expands the Planner's two-to-three candidate set with
deterministically-generated alternatives and ranks them through the
injected KPI evaluator. Numerical decision authority stays with the
DCG-authoritative evaluator and clone scoring: the optimizer never
invokes a foundation model provider, never reads the Live Twin, and
never commits to Live state.

Activation is gated by G06 (#53). The simulator accepts an optional
``CandidateRanker``; when it is ``None`` the Planner's two-to-three
candidates flow through unchanged. Two algorithms are shipped:
``heuristic_v1`` (generate, score, sort) and ``lp_v1`` (a linear-
programming relaxation proxy that pre-ranks candidates by weighted
sales impact before the KPI evaluator runs).
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from retailtwin_api.agents.simulator.branch import (
    CandidateEvaluator,
    LiveView,
    SlotView,
)
from retailtwin_api.contracts import (
    ActionUnion,
    ChangeFacings,
    Decision,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
)

log = logging.getLogger(__name__)

# The Planner's bound is 2-3 candidates; the ranker default matches that
# lower bound and gives the optimizer room to add up to a few alternatives.
DEFAULT_MAX_CANDIDATES = 8
PLANNER_MIN_CANDIDATES = 2

# Feasibility reason codes exposed in ``RankedCandidate.feasibility``.
FEASIBLE = "feasible"
INFEASIBLE_REPLENISH_OVER_BACKROOM = "replenish_exceeds_backroom"
INFEASIBLE_FACINGS_NONPOSITIVE = "facings_non_positive"
INFEASIBLE_SLOT_OCCUPIED = "destination_slot_occupied"
INFEASIBLE_SLOT_UNKNOWN = "destination_slot_unknown"
INFEASIBLE_SAME_SLOT_MOVE = "same_slot_move"
INFEASIBLE_MIXED_SKU = "actions_target_mixed_skus"
INFEASIBLE_INVALID_ACTION = "unknown_action_type"

# Deterministic action order applied when ranking: replenish first (covers
# demand), then facings (changes the cap), then moves (last resort).
_ACTION_RANK: dict[str, int] = {
    "replenish_shelf": 0,
    "change_facings": 1,
    "move_product": 2,
}


class OptimizerError(Exception):
    """The optimizer cannot rank or generate candidates."""


class InvalidRankerConfig(ValueError):
    """The ranker configuration is invalid."""


@dataclass(frozen=True)
class CandidateDraft:
    """An optimizer-side candidate, before the ranker scores it.

    ``source`` records whether the Planner produced it ("planner") or the
    optimizer generated it ("optimizer"). ``provenance`` names the generator
    that minted this draft; the value is stable for the same inputs.
    """

    candidate_id: str
    source: Literal["planner", "optimizer"]
    sku: str
    slot_id: str
    actions: tuple[ActionUnion, ...]
    rationale: str
    provenance: str


@dataclass(frozen=True)
class RankedCandidate:
    """A candidate with the ranker-computed score, rationale, and feasibility."""

    candidate_id: str
    source: Literal["planner", "optimizer"]
    sku: str
    slot_id: str
    actions: tuple[ActionUnion, ...]
    score: float
    rationale: str
    feasibility: dict[str, Any]
    rank: int
    provenance: str


@dataclass(frozen=True)
class CandidateRanker:
    """Ranker configuration. ``max_candidates`` caps the output size."""

    algorithm: Literal["heuristic_v1", "lp_v1"] = "heuristic_v1"
    max_candidates: int = DEFAULT_MAX_CANDIDATES

    def __post_init__(self) -> None:
        if self.algorithm not in ("heuristic_v1", "lp_v1"):
            raise InvalidRankerConfig(f"unknown algorithm: {self.algorithm!r}")
        if not isinstance(self.max_candidates, int) or self.max_candidates < PLANNER_MIN_CANDIDATES:
            raise InvalidRankerConfig(
                f"max_candidates must be an integer of at least {PLANNER_MIN_CANDIDATES}, "
                f"got {self.max_candidates!r}"
            )


class _RankerAlgorithm(Protocol):
    """Optional pre-rank hook used by ``lp_v1`` to bias the input order."""

    def pre_rank(
        self,
        drafts: Sequence[CandidateDraft],
        snapshot: LiveView,
    ) -> list[CandidateDraft]: ...


# --- Public helpers ---------------------------------------------------------


def _ranker_algorithm(ranker: CandidateRanker) -> _RankerAlgorithm | None:
    if ranker.algorithm == "lp_v1":
        return _LpRelaxationV1()
    return None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _whole(value: object, minimum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return number


def _slot_for_sku(snapshot: LiveView, sku: str) -> SlotView | None:
    """Return the slot holding ``sku`` if it is in the snapshot."""

    for slot in snapshot.slots:
        if slot.sku == sku:
            return slot
    return None


def _free_destinations(snapshot: LiveView, sku: str) -> tuple[SlotView, ...]:
    """Slots in the snapshot that are not currently holding any SKU.

    Moves can only target vacant shelf positions. A move into a slot
    that already holds a different SKU would overwrite that SKU, so
    occupied slots are excluded from the candidate set before ranking
    and the feasibility check never has to reject them. The candidate
    id uses ``to_slot``, so the result is sorted by ``slot_id`` for
    determinism.
    """

    return tuple(sorted(
        (slot for slot in snapshot.slots if not slot.sku.strip()),
        key=lambda item: item.slot_id,
    ))


# --- Feasibility ------------------------------------------------------------


def _check_feasibility(
    actions: Sequence[ActionUnion],
    snapshot: LiveView,
    *,
    focal_sku: str,
) -> dict[str, Any]:
    """Validate ``actions`` against the snapshot's shelf capacity and slot use.

    The check never raises. Infeasible candidates still flow through the
    ranker so the operator can see why each draft was rejected; the ranker
    surfaces them after the feasible ones.
    """

    reasons: list[str] = []
    if not actions:
        return {
            "feasible": True,
            "reasons": reasons,
            "backroom_after": None,
            "facings_after": None,
            "slot_after": None,
        }
    target_skus = {action.sku for action in actions if hasattr(action, "sku")}
    if len(target_skus) != 1 or focal_sku not in target_skus:
        reasons.append(INFEASIBLE_MIXED_SKU)
    slot_view = _slot_for_sku(snapshot, focal_sku)
    backroom_after = slot_view.backroom_quantity if slot_view is not None else None
    facings_after = slot_view.facings if slot_view is not None else None
    slot_after = slot_view.slot_id if slot_view is not None else None
    occupied_slots = {slot.slot_id for slot in snapshot.slots}
    # Slots actually holding a different SKU. Vacant slots (slot.sku is
    # empty) and the focal SKU's slot are NOT occupied and can receive
    # a move.
    occupied_after: set[str] = {
        slot.slot_id
        for slot in snapshot.slots
        if slot.sku.strip() and slot.sku.strip() != focal_sku
    }
    for action in actions:
        if isinstance(action, ReplenishShelf):
            quantity = action.quantity
            if backroom_after is None or quantity > backroom_after:
                reasons.append(INFEASIBLE_REPLENISH_OVER_BACKROOM)
            else:
                backroom_after = backroom_after - quantity
            continue
        if isinstance(action, ChangeFacings):
            if action.facings < 1:
                reasons.append(INFEASIBLE_FACINGS_NONPOSITIVE)
            else:
                facings_after = action.facings
            continue
        if isinstance(action, MoveProduct):
            if action.from_slot != slot_after:
                reasons.append(INFEASIBLE_SLOT_UNKNOWN)
            elif action.to_slot == action.from_slot:
                reasons.append(INFEASIBLE_SAME_SLOT_MOVE)
            elif action.to_slot not in occupied_slots:
                reasons.append(INFEASIBLE_SLOT_UNKNOWN)
            elif action.to_slot in occupied_after and action.to_slot != action.from_slot:
                reasons.append(INFEASIBLE_SLOT_OCCUPIED)
            else:
                occupied_after.discard(action.from_slot)
                occupied_after.add(action.to_slot)
                slot_after = action.to_slot
            continue
        reasons.append(INFEASIBLE_INVALID_ACTION)
    return {
        "feasible": not reasons,
        "reasons": reasons,
        "backroom_after": backroom_after,
        "facings_after": facings_after,
        "slot_after": slot_after,
    }


# --- Draft generation -------------------------------------------------------


def _replenish_drafts(
    sku: str,
    slot: SlotView,
    *,
    intent: str | None,
) -> tuple[CandidateDraft, ...]:
    """Replenish variants up to backroom capacity."""

    if slot.backroom_quantity <= 0:
        return ()
    backroom = slot.backroom_quantity
    # Deterministic fractional quantities, deduped and sorted. Always include
    # the full-backroom pull so the ranker can pick the most aggressive move.
    fractions = (backroom, max(1, backroom // 2), max(1, backroom // 4))
    quantities = sorted({qty for qty in fractions if 1 <= qty <= backroom})
    drafts: list[CandidateDraft] = []
    for qty in quantities:
        drafts.append(
            CandidateDraft(
                candidate_id=f"opt-{sku}-{slot.slot_id}-replenish-{qty}",
                source="optimizer",
                sku=sku,
                slot_id=slot.slot_id,
                actions=(ReplenishShelf(sku=sku, quantity=qty),),
                rationale=(
                    f"Replenish {qty} unit{'s' if qty != 1 else ''} of {sku} onto {slot.slot_id} "
                    f"({intent or 'deterministic LP relax'})."
                ),
                provenance="optimizer-heuristic-v1-replenish",
            )
        )
    return tuple(drafts)


def _facings_drafts(
    sku: str,
    slot: SlotView,
    *,
    intent: str | None,
) -> tuple[CandidateDraft, ...]:
    """Facing variants in a deterministic range."""

    candidates_set = sorted({1, slot.facings, slot.facings + 1, slot.facings + 2})
    drafts: list[CandidateDraft] = []
    for facings in candidates_set:
        if facings < 1:
            continue
        drafts.append(
            CandidateDraft(
                candidate_id=f"opt-{sku}-{slot.slot_id}-facings-{facings}",
                source="optimizer",
                sku=sku,
                slot_id=slot.slot_id,
                actions=(ChangeFacings(sku=sku, facings=facings),),
                rationale=(
                    f"Set {sku} to {facings} facing{'s' if facings != 1 else ''} on {slot.slot_id} "
                    f"({intent or 'deterministic LP relax'})."
                ),
                provenance="optimizer-heuristic-v1-facings",
            )
        )
    return tuple(drafts)


def _move_drafts(
    sku: str,
    slot: SlotView,
    snapshot: LiveView,
    *,
    intent: str | None,
) -> tuple[CandidateDraft, ...]:
    """Move candidates to slots whose id sorts strictly after the origin."""

    drafts: list[CandidateDraft] = []
    for dest in _free_destinations(snapshot, sku):
        if dest.slot_id <= slot.slot_id:
            continue
        drafts.append(
            CandidateDraft(
                candidate_id=f"opt-{sku}-{slot.slot_id}-move-{dest.slot_id}",
                source="optimizer",
                sku=sku,
                slot_id=slot.slot_id,
                actions=(MoveProduct(sku=sku, from_slot=slot.slot_id, to_slot=dest.slot_id),),
                rationale=(
                    f"Move {sku} from {slot.slot_id} to {dest.slot_id} "
                    f"({intent or 'deterministic LP relax'})."
                ),
                provenance="optimizer-heuristic-v1-move",
            )
        )
    return tuple(drafts)


def _combo_drafts(
    sku: str,
    slot: SlotView,
    *,
    intent: str | None,
) -> tuple[CandidateDraft, ...]:
    """Replenish + facings combinations."""

    if slot.backroom_quantity <= 0:
        return ()
    qty = min(4, slot.backroom_quantity)
    facings_options = sorted({slot.facings + 2, max(1, slot.facings - 1)})
    drafts: list[CandidateDraft] = []
    for facings in facings_options:
        if facings < 1 or facings == slot.facings:
            continue
        drafts.append(
            CandidateDraft(
                candidate_id=f"opt-{sku}-{slot.slot_id}-combo-{qty}-{facings}",
                source="optimizer",
                sku=sku,
                slot_id=slot.slot_id,
                actions=(
                    ChangeFacings(sku=sku, facings=facings),
                    ReplenishShelf(sku=sku, quantity=qty),
                ),
                rationale=(
                    f"Change {sku} to {facings} facings and replenish {qty} on {slot.slot_id} "
                    f"({intent or 'deterministic LP relax'})."
                ),
                provenance="optimizer-heuristic-v1-combo",
            )
        )
    return tuple(drafts)


def generate_additional_candidates(
    snapshot: LiveView,
    *,
    intent: str | None = None,
) -> list[CandidateDraft]:
    """Generate deterministic optimizer candidates for every SKU in the snapshot.

    The optimizer does not read the Live Twin. The snapshot is whatever the
    caller (the ranker) already holds; this function only inspects it.
    Determinism is the iteration order of ``snapshot.slots`` (a tuple) plus
    the deterministic ``slot_id`` ordering used inside each helper.
    """

    drafts: list[CandidateDraft] = []
    for slot in snapshot.slots:
        drafts.extend(_replenish_drafts(slot.sku, slot, intent=intent))
        drafts.extend(_facings_drafts(slot.sku, slot, intent=intent))
        drafts.extend(_move_drafts(slot.sku, slot, snapshot, intent=intent))
        drafts.extend(_combo_drafts(slot.sku, slot, intent=intent))
    return drafts


def _planner_drafts(plan: Sequence[Decision], snapshot: LiveView) -> list[CandidateDraft]:
    """Turn the Planner's Decisions into optimizer drafts."""

    drafts: list[CandidateDraft] = []
    for decision in plan:
        if not decision.proposed_actions:
            continue
        sku = decision.proposed_actions[0].sku
        slot = _slot_for_sku(snapshot, sku)
        slot_id = slot.slot_id if slot is not None else ""
        drafts.append(
            CandidateDraft(
                candidate_id=decision.decision_id,
                source="planner",
                sku=sku,
                slot_id=slot_id,
                actions=tuple(decision.proposed_actions),
                rationale=decision.expected_impact.description,
                provenance="planner-v1",
            )
        )
    return drafts


# --- LP relaxation ----------------------------------------------------------


class _LpRelaxationV1:
    """Pre-rank candidates with a velocity × price proxy.

    The ``lp_v1`` algorithm treats each candidate's expected impact as a
    linear function of its post-action shelf quantity times the slot's
    sales velocity and price. This is the LP relaxation: marginal impact
    is independent across actions. The proxy sorts the input drafts so
    the more promising ones hit the KPI evaluator first; the final order
    is still the evaluator's score.
    """

    def pre_rank(
        self,
        drafts: Sequence[CandidateDraft],
        snapshot: LiveView,
    ) -> list[CandidateDraft]:
        weights: dict[str, Decimal] = {}
        for slot in snapshot.slots:
            velocity = _decimal(slot.sales_velocity_units_per_hour)
            price = _decimal(slot.price)
            if velocity is None or price is None:
                continue
            weights[slot.slot_id] = velocity * price
        scored: list[tuple[tuple[int, Decimal, int, str], CandidateDraft]] = []
        for index, draft in enumerate(drafts):
            weight = weights.get(draft.slot_id, Decimal(0))
            best_action_rank = min(
                _ACTION_RANK.get(type(action).__name__, 99) for action in draft.actions
            ) if draft.actions else 99
            scored.append(((0, weight, -best_action_rank, draft.candidate_id), draft))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [draft for _, draft in scored]


# --- Ranker ------------------------------------------------------------------


def _score_draft(
    draft: CandidateDraft,
    snapshot_payload: Mapping[str, Any],
    *,
    simulation_id: str,
    evaluate: CandidateEvaluator,
) -> float:
    """Call ``evaluate`` on ``draft`` and return the business score as float."""

    actions_payload = [_action_to_payload(action) for action in draft.actions]
    raw = evaluate(copy.deepcopy(snapshot_payload), draft.candidate_id, actions_payload)
    if not isinstance(raw, Mapping):
        raise OptimizerError("evaluator returned a non-mapping result")
    formula_id = raw.get("formula_id")
    candidate_id = raw.get("candidate_id")
    reported_simulation_id = raw.get("simulation_id")
    if formula_id != "simulation-kpi-v1" or candidate_id != draft.candidate_id:
        raise OptimizerError("evaluator result does not match this candidate")
    if reported_simulation_id is not None and reported_simulation_id != simulation_id:
        raise OptimizerError("evaluator result does not match this simulation")
    business_score = raw.get("business_score")
    if not isinstance(business_score, str):
        raise OptimizerError("evaluator result is missing business_score")
    try:
        number = Decimal(business_score)
    except InvalidOperation:
        raise OptimizerError("evaluator business_score is not a decimal") from None
    if not number.is_finite():
        raise OptimizerError("evaluator business_score is not finite")
    return float(number)


def _snapshot_payload(snapshot: LiveView, simulation_id: str) -> dict[str, Any]:
    return {
        "simulation_id": simulation_id,
        "store_id": snapshot.store_id.strip(),
        "context_version": snapshot.context_version.strip(),
        "correlation_id": snapshot.correlation_id.strip(),
        "observed_at": snapshot.observed_at.isoformat(),
        "slots": [
            {
                "sku": slot.sku.strip(),
                "slot_id": slot.slot_id.strip(),
                "shelf_quantity": slot.shelf_quantity,
                "backroom_quantity": slot.backroom_quantity,
                "facings": slot.facings,
                "sales_velocity_units_per_hour": slot.sales_velocity_units_per_hour.strip(),
                "price": slot.price.strip(),
            }
            for slot in snapshot.slots
        ],
    }


def _action_to_payload(action: ActionUnion) -> dict[str, Any]:
    if isinstance(action, ReplenishShelf):
        return {"type": "replenish_shelf", "sku": action.sku, "quantity": action.quantity}
    if isinstance(action, ChangeFacings):
        return {"type": "change_facings", "sku": action.sku, "facings": action.facings}
    if isinstance(action, MoveProduct):
        return {
            "type": "move_product",
            "sku": action.sku,
            "from_slot": action.from_slot,
            "to_slot": action.to_slot,
        }
    raise OptimizerError(f"unknown action type: {type(action).__name__}")


def _focal_sku(plan: Sequence[Decision]) -> str | None:
    for decision in plan:
        for action in decision.proposed_actions:
            if hasattr(action, "sku"):
                return action.sku
    return None


def _dedupe_drafts(drafts: Sequence[CandidateDraft]) -> list[CandidateDraft]:
    """Drop duplicate candidate ids deterministically."""

    seen: set[str] = set()
    unique: list[CandidateDraft] = []
    for draft in drafts:
        if draft.candidate_id in seen:
            continue
        seen.add(draft.candidate_id)
        unique.append(draft)
    return unique


def rank_candidates(
    plan: Sequence[Decision],
    live_snapshot: LiveView,
    *,
    kpi_evaluator: CandidateEvaluator,
    ranker: CandidateRanker,
    intent: str | None = None,
    simulation_id: str | None = None,
) -> list[RankedCandidate]:
    """Expand ``plan``, score each candidate, return the top-``max_candidates`` by KPI.

    The same ``kpi_evaluator`` used by the simulator scores every candidate
    on a deterministic clone of ``live_snapshot``. Feasibility is checked
    against the snapshot's shelf capacity, backroom quantity, and slot
    uniqueness. The output is deterministic: identical inputs produce the
    same rank order, the same scores, and the same feasibility map.
    """

    if not isinstance(live_snapshot, LiveView):
        raise OptimizerError("live_snapshot must be a LiveView")
    if not isinstance(ranker, CandidateRanker):
        raise OptimizerError("ranker must be a CandidateRanker")
    if not callable(kpi_evaluator):
        raise OptimizerError("kpi_evaluator must be callable")

    correlation_id = _text(live_snapshot.correlation_id) or "unknown"
    focal_sku = _focal_sku(plan) or ""
    sim_id = simulation_id or f"sim-opt-{correlation_id}-{focal_sku or 'plan'}"

    pool = _dedupe_drafts(_planner_drafts(plan, live_snapshot) + generate_additional_candidates(live_snapshot, intent=intent))
    if focal_sku:
        pool = [draft for draft in pool if draft.sku == focal_sku]
    if not pool:
        return []

    algorithm = _ranker_algorithm(ranker)
    ordered = list(pool)
    if algorithm is not None:
        ordered = algorithm.pre_rank(ordered, live_snapshot)

    payload = _snapshot_payload(live_snapshot, sim_id)

    scored: list[tuple[RankedCandidate, bool]] = []
    for draft in ordered:
        feasibility = _check_feasibility(draft.actions, live_snapshot, focal_sku=draft.sku)
        feasible = bool(feasibility.get("feasible"))
        if feasible:
            try:
                score = _score_draft(
                    draft, payload, simulation_id=sim_id, evaluate=kpi_evaluator
                )
            except OptimizerError as exc:
                log.info(
                    "optimizer dropped candidate_id=%s sku=%s reason=%s",
                    draft.candidate_id,
                    draft.sku,
                    str(exc),
                )
                continue
            score_value = score
        else:
            score_value = float("-inf")
        scored.append((
            RankedCandidate(
                candidate_id=draft.candidate_id,
                source=draft.source,
                sku=draft.sku,
                slot_id=draft.slot_id,
                actions=draft.actions,
                score=score_value,
                rationale=draft.rationale,
                feasibility=feasibility,
                rank=0,
                provenance=draft.provenance,
            ),
            feasible,
        ))

    # Deterministic ordering: higher score first, feasible before infeasible,
    # then by candidate_id as a stable tie-breaker.
    scored.sort(
        key=lambda pair: (
            -pair[0].score,
            0 if pair[1] else 1,
            pair[0].candidate_id,
        )
    )
    top = scored[: ranker.max_candidates]
    ranked = [
        RankedCandidate(
            candidate_id=item.candidate_id,
            source=item.source,
            sku=item.sku,
            slot_id=item.slot_id,
            actions=item.actions,
            score=item.score,
            rationale=item.rationale,
            feasibility=item.feasibility,
            rank=index + 1,
            provenance=item.provenance,
        )
        for index, (item, _) in enumerate(top)
    ]
    return ranked


# --- Decision conversion ----------------------------------------------------


def ranked_to_decision(
    ranked: RankedCandidate,
    *,
    base: Decision,
    agent_id: str = "retailtwin-optimizer",
) -> Decision:
    """Wrap a ``RankedCandidate`` as a ``Decision`` for the simulator.

    The base decision supplies ``context_version``, ``context_timestamp``,
    and ``evidence`` so the optimizer's output keeps the binding the
    Planner set up. ``expected_impact.kpi_score`` is the ranker's score;
    the simulator still scores the same way and produces the same value.
    """

    return base.model_copy(
        update={
            "decision_id": ranked.candidate_id,
            "agent_id": agent_id,
            "proposed_actions": list(ranked.actions),
            "simulation_id": None,
            "expected_impact": ExpectedImpact(
                kpi_score=ranked.score,
                description=ranked.rationale,
            ),
        }
    )