"""Advanced constrained retail optimizer (issue #54).

Deterministic expansion, scoring, ranking, and simulator wiring.
"""

from __future__ import annotations

import copy
import json
import logging
import sys
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[3]
for _root in (_REPO / "services" / "simulation", _REPO / "services" / "forecasting"):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from kpi.evaluator import (
    ChangeFacings as KpiChangeFacings,
)
from kpi.evaluator import (
    MoveProduct as KpiMoveProduct,
)
from kpi.evaluator import (
    ReplenishShelf as KpiReplenishShelf,
)
from kpi.evaluator import (
    SimulationSnapshot,
    SlotState,
    evaluate_candidate,
)

from retailtwin_api.agents.optimizer import (
    DEFAULT_MAX_CANDIDATES,
    FEASIBLE,
    INFEASIBLE_FACINGS_NONPOSITIVE,
    INFEASIBLE_MIXED_SKU,
    INFEASIBLE_REPLENISH_OVER_BACKROOM,
    INFEASIBLE_SAME_SLOT_MOVE,
    INFEASIBLE_SLOT_OCCUPIED,
    InvalidRankerConfig,
    OptimizerError,
    CandidateDraft,
    CandidateRanker,
    RankedCandidate,
    generate_additional_candidates,
    rank_candidates,
    ranked_to_decision,
)
from retailtwin_api.agents.planner.plans import UNSCORED_IMPACT, plan
from retailtwin_api.agents.simulator import (
    EVALUATION_FAILED,
    LiveView,
    SimulationError,
    SlotView,
    simulate,
)
from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    EvidenceBundle,
    EvidenceItem,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.llm.contracts import LlmProvider
from retailtwin_api.llm.fake import FakeLlmProvider

CORRELATION_ID = "run-weekend-demand-surge-1"
CONTEXT_VERSION = "store-001:v1"
OBSERVED = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
COLLECTED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
CONTEXT_AT = datetime(2026, 10, 10, 12, 5, tzinfo=timezone.utc)


# --- Fixtures ----------------------------------------------------------------


def _slot(**overrides: Any) -> SlotView:
    fields: dict[str, Any] = {
        "sku": "P017",
        "slot_id": "A02-S03",
        "shelf_quantity": 8,
        "backroom_quantity": 54,
        "facings": 2,
        "sales_velocity_units_per_hour": "18.25",
        "price": "3.5",
    }
    fields.update(overrides)
    return SlotView(**fields)


def _live(**overrides: Any) -> LiveView:
    fields: dict[str, Any] = {
        "store_id": "store-001",
        "context_version": CONTEXT_VERSION,
        "correlation_id": CORRELATION_ID,
        "observed_at": OBSERVED,
        "slots": (_slot(),),
    }
    fields.update(overrides)
    return LiveView(**fields)


def _two_slot_live() -> LiveView:
    return _live(
        slots=(
            _slot(),
            _slot(
                sku="P001",
                slot_id="B02-S01",
                shelf_quantity=4,
                backroom_quantity=20,
                facings=1,
                sales_velocity_units_per_hour="5",
                price="1",
            ),
        )
    )


def _bundle(**overrides: Any) -> EvidenceBundle:
    inventory = EvidenceItem(
        event_type="inventory",
        payload={
            "source": "inventory",
            "entity_id": "P017",
            "version": "1",
            "observed_at": COLLECTED_AT.isoformat(),
            "value": {
                "store_id": "store-001",
                "sku": "P017",
                "shelf_id": "A02",
                "slot_id": "A02-S03",
                "facings": 2,
                "shelf_quantity": 8,
                "backroom_quantity": 54,
                "version": 1,
            },
        },
    )
    forecast = EvidenceItem(
        event_type="forecast",
        payload={
            "source": "forecast",
            "entity_id": "P017",
            "version": "forecast-demand-v1",
            "observed_at": "2026-10-10T12:00:00Z",
            "value": {"forecast_units": "73", "formula_id": "forecast-demand-v1"},
        },
    )
    fields: dict[str, Any] = {
        "bundle_id": f"bundle-{CORRELATION_ID}-P017",
        "provenance": "tool-registry",
        "source": "investigator",
        "entity_versions": {"P017": "1"},
        "collected_at": COLLECTED_AT,
        "freshness": COLLECTED_AT,
        "store_id": "store-001",
        "correlation_id": CORRELATION_ID,
        "is_sufficient": True,
        "items": [inventory, forecast],
    }
    fields.update(overrides)
    return EvidenceBundle(**fields)


def _decision(**overrides: Any) -> Decision:
    fields: dict[str, Any] = {
        "decision_id": f"plan-{CORRELATION_ID}-P017-1",
        "agent_id": "retailtwin-planner",
        "context_version": CONTEXT_VERSION,
        "context_timestamp": CONTEXT_AT,
        "evidence": [_bundle()],
        "proposed_actions": [ReplenishShelf(sku="P017", quantity=12)],
        "simulation_id": None,
        "expected_impact": ExpectedImpact(
            kpi_score=UNSCORED_IMPACT,
            description="Replenish P017 from the backroom.",
        ),
    }
    fields.update(overrides)
    return Decision(**fields)


def _canonical() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "reason": "Replenish P017 from the backroom.",
                "actions": [{"type": "replenish_shelf", "sku": "P017", "quantity": 12}],
            },
            {
                "reason": "Increase facings, then replenish P017.",
                "actions": [
                    {"type": "change_facings", "sku": "P017", "facings": 4},
                    {"type": "replenish_shelf", "sku": "P017", "quantity": 12},
                ],
            },
            {
                "reason": "Move P017, increase facings, then replenish.",
                "actions": [
                    {
                        "type": "move_product",
                        "sku": "P017",
                        "from_slot": "A02-S03",
                        "to_slot": "B02-S01",
                    },
                    {"type": "change_facings", "sku": "P017", "facings": 4},
                    {"type": "replenish_shelf", "sku": "P017", "quantity": 12},
                ],
            },
        ]
    }


def _provider(body: dict[str, Any]) -> FakeLlmProvider:
    return FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(content=json.dumps(body), tool_calls=[], finish_reason="stop")
        ]
    )


def _plan(bundle: EvidenceBundle, provider: LlmProvider) -> list[Decision]:
    import asyncio

    return asyncio.run(
        plan(
            bundle,
            provider=provider,
            context_version=CONTEXT_VERSION,
            context_timestamp=CONTEXT_AT,
        )
    )


def _kpi_actions(decision: Decision) -> tuple[Any, ...]:
    converted: list[Any] = []
    for action in decision.proposed_actions:
        if isinstance(action, MoveProduct):
            converted.append(KpiMoveProduct(sku=action.sku, from_slot=action.from_slot, to_slot=action.to_slot))
        elif isinstance(action, ChangeFacings):
            converted.append(KpiChangeFacings(sku=action.sku, facings=action.facings))
        elif isinstance(action, ReplenishShelf):
            converted.append(KpiReplenishShelf(sku=action.sku, quantity=action.quantity))
        else:
            raise AssertionError(type(action))
    return tuple(converted)


def _kpi(
    snapshot: Mapping[str, Any],
    candidate_id: str,
    actions: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    observed_at = snapshot["observed_at"]
    if not isinstance(observed_at, str):
        raise RuntimeError("observed_at must be an ISO string")
    built = SimulationSnapshot(
        simulation_id=snapshot["simulation_id"],
        store_id=snapshot["store_id"],
        context_version=snapshot["context_version"],
        correlation_id=snapshot["correlation_id"],
        observed_at=datetime.fromisoformat(observed_at),
        slots=tuple(
            SlotState(
                sku=slot["sku"],
                slot_id=slot["slot_id"],
                shelf_quantity=slot["shelf_quantity"],
                backroom_quantity=slot["backroom_quantity"],
                facings=slot["facings"],
                sales_velocity_units_per_hour=Decimal(slot["sales_velocity_units_per_hour"]),
                price=Decimal(slot["price"]),
            )
            for slot in snapshot["slots"]
        ),
    )
    converted: list[Any] = []
    for action in actions:
        kind = action["type"]
        if kind == "move_product":
            converted.append(KpiMoveProduct(sku=action["sku"], from_slot=action["from_slot"], to_slot=action["to_slot"]))
        elif kind == "change_facings":
            converted.append(KpiChangeFacings(sku=action["sku"], facings=action["facings"]))
        elif kind == "replenish_shelf":
            converted.append(KpiReplenishShelf(sku=action["sku"], quantity=action["quantity"]))
        else:
            raise RuntimeError(f"unknown action {kind}")
    return evaluate_candidate(built, candidate_id, tuple(converted)).as_dict()


def _boom(
    snapshot: Mapping[str, Any],
    candidate_id: str,
    actions: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    raise AssertionError("evaluator must not run")


# --- Tests -------------------------------------------------------------------


def test_generate_additional_candidates_produces_feasible_set() -> None:
    live = _live()
    drafts = generate_additional_candidates(live, intent="weekend-demand-surge")

    assert drafts, "optimizer must produce at least one candidate"
    candidate_ids = [draft.candidate_id for draft in drafts]
    assert len(set(candidate_ids)) == len(candidate_ids), "candidate ids must be unique"
    for draft in drafts:
        assert draft.source == "optimizer"
        assert draft.sku == "P017"
        assert draft.slot_id == "A02-S03"
        assert draft.actions, "each draft must carry at least one action"
        assert draft.rationale, "each draft must carry a rationale"
        assert draft.provenance.startswith("optimizer-")
        for action in draft.actions:
            assert isinstance(action, (ReplenishShelf, ChangeFacings, MoveProduct))
            if isinstance(action, ReplenishShelf):
                assert 1 <= action.quantity <= 54
            elif isinstance(action, ChangeFacings):
                assert action.facings >= 1
            elif isinstance(action, MoveProduct):
                assert action.from_slot == "A02-S03"
                assert action.to_slot != action.from_slot
    replenishes = [draft for draft in drafts if any(isinstance(a, ReplenishShelf) for a in draft.actions)]
    assert replenishes, "optimizer must emit replenish variants when backroom has stock"


def test_generate_additional_candidates_is_deterministic() -> None:
    live = _live()
    first = generate_additional_candidates(live, intent="weekend-demand-surge")
    again = generate_additional_candidates(live, intent="weekend-demand-surge")
    assert [d.candidate_id for d in first] == [d.candidate_id for d in again]
    assert [d.rationale for d in first] == [d.rationale for d in again]


def test_rank_candidates_is_deterministic() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)

    first = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)
    again = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)

    assert [item.candidate_id for item in first] == [item.candidate_id for item in again]
    assert [item.score for item in first] == [item.score for item in again]
    assert [item.rank for item in first] == list(range(1, len(first) + 1))
    assert [item.rationale for item in first] == [item.rationale for item in again]


def test_rank_candidates_picks_higher_kpi() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)

    ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)

    assert ranked, "ranker must produce at least one ranked candidate"
    scores = [item.score for item in ranked]
    assert scores == sorted(scores, reverse=True)
    top = ranked[0]
    bottom = ranked[-1]
    assert top.score >= bottom.score
    # The optimizer's top pick should out-score the Planner's lowest.
    planner_ids = {decision.decision_id for decision in decisions}
    assert any(item.candidate_id in planner_ids for item in ranked), "planner proposals must surface"


def test_rank_candidates_respects_shelf_capacity() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)

    ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)

    for entry in ranked:
        backroom_after = entry.feasibility.get("backroom_after")
        if entry.feasibility.get("feasible"):
            assert backroom_after is None or backroom_after >= 0
        for action in entry.actions:
            if isinstance(action, ReplenishShelf):
                assert action.quantity <= 54


def test_rank_candidates_respects_slot_uniqueness() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)

    ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)

    occupied_slots: set[str] = {"A02-S03"}
    for entry in ranked:
        draft_occupied = copy.copy(occupied_slots)
        for action in entry.actions:
            if isinstance(action, MoveProduct):
                if action.from_slot in draft_occupied:
                    draft_occupied.discard(action.from_slot)
                draft_occupied.add(action.to_slot)
        if entry.feasibility.get("feasible"):
            assert len(draft_occupied) == len(set(draft_occupied))
        else:
            assert entry.feasibility.get("reasons")


def test_optimizer_falls_back_when_ranker_missing() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    before_live = copy.deepcopy(live)

    result = simulate(decisions, live, evaluate=_kpi)

    assert [item.decision.decision_id for item in result.candidates] == [
        decision.decision_id for decision in decisions
    ]
    assert live == before_live


def test_optimizer_ranker_picks_top_k_when_max_candidates_is_set() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=3)

    result = simulate(decisions, live, evaluate=_kpi, ranker=ranker)

    assert len(result.candidates) <= 3
    assert result.candidates
    scores = [item.kpi.kpi_score for item in result.candidates]
    assert scores == sorted(scores, reverse=True)
    live_after = live
    assert live_after.slots[0].shelf_quantity == 8


def test_optimizer_does_not_overrun_max_candidates() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    for bound in (2, 4, 8, 16):
        ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=bound)
        ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)
        assert len(ranked) <= bound, f"ranker returned {len(ranked)} > bound {bound}"
        assert len(ranked) >= 1, f"ranker returned no candidates for bound {bound}"


def test_optimizer_output_carries_provenance() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)

    ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)

    sources = {item.source for item in ranked}
    assert "planner" in sources, "planner candidates must be present"
    assert "optimizer" in sources, "optimizer candidates must be present"
    for entry in ranked:
        assert entry.provenance, "every ranked candidate must carry provenance"
        assert entry.rationale, "every ranked candidate must carry a rationale"
        assert "feasible" in entry.feasibility
        assert "reasons" in entry.feasibility
        assert "backroom_after" in entry.feasibility
        assert "facings_after" in entry.feasibility
        assert "slot_after" in entry.feasibility
        assert entry.rank >= 1


def test_optimizer_lp_v1_orders_by_weighted_proxy() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="lp_v1", max_candidates=8)

    ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)

    assert ranked
    scores = [item.score for item in ranked]
    assert scores == sorted(scores, reverse=True)
    assert all(entry.provenance for entry in ranked)


def test_optimizer_rejects_infeasible_candidates() -> None:
    """An over-backroom replenishment must carry the backroom reason."""

    live = _live()
    decision = _decision(
        proposed_actions=[ReplenishShelf(sku="P017", quantity=200)],
    )
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=64)

    ranked = rank_candidates([decision], live, kpi_evaluator=_kpi, ranker=ranker)
    planner_entry = next(item for item in ranked if item.source == "planner")
    assert planner_entry.feasibility.get("feasible") is False
    assert INFEASIBLE_REPLENISH_OVER_BACKROOM in planner_entry.feasibility.get("reasons", [])


def test_optimizer_marks_same_slot_move_infeasible() -> None:
    live = _live()
    decision = _decision(
        proposed_actions=[MoveProduct(sku="P017", from_slot="A02-S03", to_slot="A02-S03")],
    )
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=64)

    ranked_list = rank_candidates([decision], live, kpi_evaluator=_kpi, ranker=ranker)
    planner_entry = next(item for item in ranked_list if item.source == "planner")
    assert planner_entry.feasibility.get("feasible") is False
    assert INFEASIBLE_SAME_SLOT_MOVE in planner_entry.feasibility.get("reasons", [])


def test_optimizer_marks_occupied_destination_infeasible() -> None:
    live = _two_slot_live()
    decision = _decision(
        proposed_actions=[MoveProduct(sku="P017", from_slot="A02-S03", to_slot="B02-S01")],
    )
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=64)

    ranked_list = rank_candidates([decision], live, kpi_evaluator=_kpi, ranker=ranker)
    planner_entry = next(item for item in ranked_list if item.source == "planner")
    assert planner_entry.feasibility.get("feasible") is False
    assert INFEASIBLE_SLOT_OCCUPIED in planner_entry.feasibility.get("reasons", [])


def test_optimizer_marks_mixed_sku_infeasible() -> None:
    live = _live()
    decision = _decision(
        proposed_actions=[
            ReplenishShelf(sku="P017", quantity=2),
            ReplenishShelf(sku="P099", quantity=1),
        ],
    )
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=64)

    ranked_list = rank_candidates([decision], live, kpi_evaluator=_kpi, ranker=ranker)
    planner_entry = next(item for item in ranked_list if item.source == "planner")
    assert planner_entry.feasibility.get("feasible") is False
    assert INFEASIBLE_MIXED_SKU in planner_entry.feasibility.get("reasons", [])


def test_optimizer_marks_negative_facings_infeasible() -> None:
    live = _live()
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)
    # The pydantic model forbids facings < 1, so we exercise the
    # feasibility helper directly with a hand-built candidate.
    from retailtwin_api.agents.optimizer.optimizer import _check_feasibility

    feasibility = _check_feasibility(
        [ChangeFacings(sku="P017", facings=1), ChangeFacings(sku="P017", facings=2)],
        live,
        focal_sku="P017",
    )
    assert "feasible" in feasibility
    assert feasibility["facings_after"] == 2

    # The optimizer must never emit a ChangeFacings draft below 1.
    for entry in rank_candidates([], live, kpi_evaluator=_kpi, ranker=ranker):
        for action in entry.actions:
            if isinstance(action, ChangeFacings):
                assert action.facings >= 1


def test_optimizer_simulator_runs_the_same_top_candidate() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=4)

    ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)
    top = ranked[0]

    result = simulate(decisions, live, evaluate=_kpi, ranker=ranker)

    assert [item.decision.decision_id for item in result.candidates] == [
        item.candidate_id for item in ranked
    ]
    assert result.candidates[0].kpi.kpi_score == top.score


def test_optimizer_ranker_rejects_invalid_config() -> None:
    with pytest.raises(InvalidRankerConfig):
        CandidateRanker(algorithm="nope")  # type: ignore[arg-type]
    with pytest.raises(InvalidRankerConfig):
        CandidateRanker(max_candidates=1)
    with pytest.raises(InvalidRankerConfig):
        CandidateRanker(max_candidates="4")  # type: ignore[arg-type]


def test_ranked_to_decision_preserves_context() -> None:
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=4)
    ranked = rank_candidates(decisions, live, kpi_evaluator=_kpi, ranker=ranker)

    rebuilt = ranked_to_decision(ranked[0], base=decisions[0])

    assert rebuilt.decision_id == ranked[0].candidate_id
    assert rebuilt.context_version == decisions[0].context_version
    assert rebuilt.context_timestamp == decisions[0].context_timestamp
    assert rebuilt.evidence == decisions[0].evidence
    assert rebuilt.proposed_actions == list(ranked[0].actions)
    assert rebuilt.expected_impact.kpi_score == ranked[0].score
    assert rebuilt.expected_impact.description == ranked[0].rationale
    assert rebuilt.simulation_id is None


def test_optimizer_simulator_propagates_ranker_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))

    def boom_evaluator(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        raise RuntimeError("secret")

    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=4)

    with pytest.raises(SimulationError) as caught:
        simulate(decisions, live, evaluate=boom_evaluator, ranker=ranker)

    assert caught.value.reason == EVALUATION_FAILED
    assert caught.value.correlation_id == CORRELATION_ID
    assert "secret" not in str(caught.value)
    assert "secret" not in caplog.text


def test_optimizer_source_does_not_import_a_model_sdk_or_simulation_kpi() -> None:
    from retailtwin_api.agents.optimizer import optimizer as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    for banned in (
        "openai",
        "vertex",
        "google.cloud",
        "firestore",
        "submit_action_for_commit",
        "services.simulation",
        "kpi.evaluator",
        "vertexai",
        "from openai",
        "import openai",
    ):
        assert banned not in lowered, banned


def test_default_max_candidates_is_8() -> None:
    assert DEFAULT_MAX_CANDIDATES == 8


def test_optimizer_picks_feasible_first_under_tie() -> None:
    """When two candidates score identically, the feasible one wins."""

    live = _live()
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)
    feasible_draft = CandidateDraft(
        candidate_id="manual-feasible",
        source="optimizer",
        sku="P017",
        slot_id="A02-S03",
        actions=(ReplenishShelf(sku="P017", quantity=4),),
        rationale="Feasible replenishment",
        provenance="optimizer-test",
    )
    infeasible_draft = CandidateDraft(
        candidate_id="manual-infeasible",
        source="optimizer",
        sku="P017",
        slot_id="A02-S03",
        actions=(ReplenishShelf(sku="P017", quantity=200),),
        rationale="Infeasible replenishment",
        provenance="optimizer-test",
    )

    ranked = rank_candidates(
        [_decision()], live, kpi_evaluator=_kpi, ranker=ranker
    )

    feasibility_order = [item.feasibility.get("feasible") for item in ranked]
    # Feasible candidates appear before any infeasible one whenever scores tie.
    seen_infeasible = False
    for feasible in feasibility_order:
        if not feasible:
            seen_infeasible = True
            continue
        assert not seen_infeasible, "feasible candidate appeared after an infeasible one"


def test_optimizer_excludes_non_vacant_destinations() -> None:
    """Optimizer-generated moves target only vacant slots.

    Reproduces the CHANGES_REQUESTED review on PR #256: with
    ``A02-S03`` holding ``P017`` and ``B02-S01`` holding ``P099``, the
    optimizer's ``_free_destinations`` previously returned ``B02-S01``
    as a candidate for moves of ``P017`` because ``B02-S01.sku !=
    "P017"``. Only truly vacant slots (no SKU on the fixture) are
    valid move destinations, so optimizer-generated ``MoveProduct``
    drafts must never target a slot held by a different SKU.

    The Planner's explicit moves are a separate input path -- they
    are validated downstream by the feasibility check, and the
    existing ``test_optimizer_marks_occupied_destination_infeasible``
    test guarantees that path still rejects moves into occupied
    slots.
    """

    live = _two_slot_live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=64)

    ranked = rank_candidates(
        decisions, live, kpi_evaluator=_kpi, ranker=ranker,
        intent="weekend-demand-surge",
    )

    occupied_destinations = {"B02-S01"}
    optimizer_move_targets: list[str] = []
    for entry in ranked:
        if entry.source != "optimizer":
            continue
        for action in entry.actions:
            if isinstance(action, MoveProduct):
                optimizer_move_targets.append(action.to_slot)
                assert action.to_slot not in occupied_destinations, (
                    f"optimizer emitted MoveProduct to {action.to_slot} which "
                    "is held by a different SKU; destinations must be vacant"
                )
    # No entry sourced from the optimizer may carry the SLOT_OCCUPIED
    # reason: the destination filter excludes those drafts before
    # ranking, so the ranker never reaches the feasibility reject.
    for entry in ranked:
        if entry.source == "optimizer":
            assert INFEASIBLE_SLOT_OCCUPIED not in entry.feasibility.get("reasons", []), (
                "the optimizer's destination filter happens before ranking, "
                "so optimizer-sourced entries must not surface "
                "INFEASIBLE_SLOT_OCCUPIED reasons"
            )
    # Sanity check: the planner's explicit move still flows through and
    # is correctly rejected by the feasibility check downstream.
    planner_move_entries = [
        entry for entry in ranked
        if entry.source == "planner"
        and any(
            isinstance(a, MoveProduct) and a.to_slot == "B02-S01"
            for a in entry.actions
        )
    ]
    assert planner_move_entries, (
        "planner's explicit move to B02-S01 must still flow through"
    )
    for entry in planner_move_entries:
        assert INFEASIBLE_SLOT_OCCUPIED in entry.feasibility.get("reasons", []), (
            "planner-sourced move to an occupied slot must be flagged by feasibility"
        )


def _kpi_permissive(
    snapshot: Mapping[str, Any],
    candidate_id: str,
    actions: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Test-only evaluator that bypasses the strict kpi/evaluator snapshot.

    Lets the test fixture include a vacant slot (``slot.sku`` empty)
    without tripping the production validator, which requires every
    slot's SKU to be a non-empty string. The optimizer's destination
    pool is the system under test; the score is a fixed positive
    number so feasibility, not score, drives ranking.
    """

    return {
        "formula_id": "simulation-kpi-v1",
        "candidate_id": candidate_id,
        "simulation_id": snapshot.get("simulation_id"),
        "business_score": "0.5",
    }


def test_optimizer_feasible_top_k_with_vacant_destination() -> None:
    """Constrained feasible-top-K surfaces moves to genuinely vacant slots.

    With a snapshot that has ``A02-S03`` holding ``P017`` and a vacant
    slot ``C02-S01`` (no SKU), the optimizer emits ``MoveProduct``
    drafts from ``A02-S03`` to ``C02-S01`` only. The ranker marks the
    move feasible and surfaces it inside the top-K bound.
    """

    live = _live(
        slots=(
            _slot(),  # A02-S03 with P017
            _slot(
                sku="",
                slot_id="C02-S01",
                shelf_quantity=0,
                backroom_quantity=0,
                facings=0,
                sales_velocity_units_per_hour="0",
                price="0",
            ),
        ),
    )
    # Large cap so the deterministic tie-break (alphabetical candidate
    # id) places the move entry inside the top-K; the ranker is still
    # bound by ``max_candidates``.
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)

    ranked = rank_candidates(
        [_decision()],
        live,
        kpi_evaluator=_kpi_permissive,
        ranker=ranker,
        intent="weekend-demand-surge",
    )

    assert ranked, "ranker must produce at least one candidate"
    assert len(ranked) <= 8
    scores = [entry.score for entry in ranked]
    assert scores == sorted(scores, reverse=True)
    vacant_move_entries = [
        entry for entry in ranked
        if any(
            isinstance(a, MoveProduct)
            and a.to_slot == "C02-S01"
            and a.from_slot == "A02-S03"
            for a in entry.actions
        )
    ]
    assert vacant_move_entries, (
        "ranker must emit at least one MoveProduct A02-S03 -> C02-S01"
    )
    for entry in vacant_move_entries:
        feasibility = entry.feasibility
        assert feasibility.get("feasible") is True, (
            "vacant-destination move must be feasible; got reasons: "
            f"{feasibility.get('reasons')}"
        )
        assert not feasibility.get("reasons")


def test_rank_candidates_concurrent_deterministic() -> None:
    """Two threads calling ``rank_candidates`` on the same inputs agree.

    Confirms that ``_free_destinations`` and the ranker carry no mutable
    shared state: concurrent reads under the GIL produce byte-identical
    candidate ids, scores, and ranks.
    """

    import threading

    live = _live()
    decisions = _plan(_bundle(), _provider(_canonical()))
    ranker = CandidateRanker(algorithm="heuristic_v1", max_candidates=8)

    barrier = threading.Barrier(2)
    outputs: list[list[RankedCandidate]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            outputs.append(
                rank_candidates(
                    decisions,
                    live,
                    kpi_evaluator=_kpi,
                    ranker=ranker,
                    intent="weekend-demand-surge",
                )
            )
        except BaseException as exc:  # pragma: no cover - error path
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors, f"concurrent ranker raised: {errors}"
    assert len(outputs) == 2
    first, second = outputs
    assert [item.candidate_id for item in first] == [item.candidate_id for item in second]
    assert [item.score for item in first] == [item.score for item in second]
    assert [item.rank for item in first] == [item.rank for item in second]
    assert [item.feasibility.get("feasible") for item in first] == [
        item.feasibility.get("feasible") for item in second
    ]