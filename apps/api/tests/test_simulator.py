"""Simulator: score planner decisions on a clone, never the live shelf."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[3]
for _root in (_REPO / "services" / "simulation", _REPO / "services" / "forecasting"):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from kpi.evaluator import (
    FORMULA_ID as KPI_FORMULA_ID,
)
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

from retailtwin_api.agents.planner.plans import UNSCORED_IMPACT, plan
from retailtwin_api.agents.simulator import (
    CONTEXT_MISMATCH,
    EVALUATION_FAILED,
    FORMULA_ID,
    INVALID_REQUEST,
    INVALID_SNAPSHOT,
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


class _NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None


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
        responses=[FakeLlmProvider.Response(content=json.dumps(body), tool_calls=[], finish_reason="stop")]
    )


def _plan(bundle: EvidenceBundle, provider: LlmProvider) -> list[Decision]:
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
            converted.append(
                KpiMoveProduct(sku=action.sku, from_slot=action.from_slot, to_slot=action.to_slot)
            )
        elif isinstance(action, ChangeFacings):
            converted.append(KpiChangeFacings(sku=action.sku, facings=action.facings))
        elif isinstance(action, ReplenishShelf):
            converted.append(KpiReplenishShelf(sku=action.sku, quantity=action.quantity))
        else:
            raise AssertionError(type(action))
    return tuple(converted)


def _oracle(simulation_id: str, candidate_id: str, actions: Sequence[Any]) -> dict[str, Any]:
    snapshot = SimulationSnapshot(
        simulation_id=simulation_id,
        store_id="store-001",
        context_version=CONTEXT_VERSION,
        correlation_id=CORRELATION_ID,
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=8,
                backroom_quantity=54,
                facings=2,
                sales_velocity_units_per_hour=Decimal("18.25"),
                price=Decimal("3.5"),
            ),
        ),
    )
    return evaluate_candidate(snapshot, candidate_id, actions).as_dict()


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
            converted.append(
                KpiMoveProduct(sku=action["sku"], from_slot=action["from_slot"], to_slot=action["to_slot"])
            )
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


def test_weekend_plans_are_scored_on_a_clone_of_the_live_shelf(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    live = _live()
    before_live = copy.deepcopy(live)
    decisions = _plan(_bundle(), _provider(_canonical()))
    before_decisions = [item.model_dump(mode="json") for item in decisions]
    seen: list[dict[str, Any]] = []
    identities: list[int] = []

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        assert type(snapshot) is dict
        assert snapshot["slots"][0]["shelf_quantity"] == 8
        assert "forecast_units_per_hour" not in snapshot["slots"][0]
        assert all(type(action) is dict for action in actions)
        identities.append(id(snapshot))
        seen.append({"candidate_id": candidate_id, "actions": [dict(action) for action in actions]})
        scored = _kpi(snapshot, candidate_id, actions)
        snapshot["slots"][0]["shelf_quantity"] = 0
        snapshot["slots"][0]["slot_id"] = "mutated"
        return scored

    result = simulate(decisions, live, evaluate=evaluate)
    again = simulate(decisions, live, evaluate=evaluate)

    assert FORMULA_ID == KPI_FORMULA_ID == "simulation-kpi-v1"
    assert result.simulation_id == f"sim-{CORRELATION_ID}"
    assert result.context_version == CONTEXT_VERSION
    assert result.correlation_id == CORRELATION_ID
    assert [item.decision_id for item in decisions] == [
        f"plan-{CORRELATION_ID}-P017-1",
        f"plan-{CORRELATION_ID}-P017-2",
        f"plan-{CORRELATION_ID}-P017-3",
    ]
    assert seen[:3] == [
        {
            "candidate_id": decisions[0].decision_id,
            "actions": [{"type": "replenish_shelf", "sku": "P017", "quantity": 12}],
        },
        {
            "candidate_id": decisions[1].decision_id,
            "actions": [
                {"type": "change_facings", "sku": "P017", "facings": 4},
                {"type": "replenish_shelf", "sku": "P017", "quantity": 12},
            ],
        },
        {
            "candidate_id": decisions[2].decision_id,
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
    assert len(set(identities[:3])) == 3
    for original, scored in zip(decisions, result.candidates, strict=True):
        oracle = _oracle(result.simulation_id, original.decision_id, _kpi_actions(original))
        assert scored.evaluation == oracle
        assert scored.kpi.simulation_id == result.simulation_id
        assert scored.kpi.kpi_score == float(Decimal(str(oracle["business_score"])))
        assert scored.kpi.duration_ms >= 0
        assert scored.decision.simulation_id == result.simulation_id
        assert scored.decision.expected_impact.kpi_score == scored.kpi.kpi_score
        assert scored.decision.expected_impact.description == original.expected_impact.description
        assert scored.decision.proposed_actions == original.proposed_actions
        assert scored.decision.evidence == original.evidence
        assert original.simulation_id is None
        assert original.expected_impact.kpi_score == UNSCORED_IMPACT
    assert [item.evaluation["business_score"] for item in result.candidates] == ["0.12", "0.09", "0.07"]
    assert result.candidates[0].evaluation["service_level"] == "0.27"
    assert result.candidates[0].evaluation["stockout_risk"] == "0.15"
    assert [item.evaluation["movement_units"] for item in result.candidates] == ["12", "14", "15"]
    assert [item.model_dump(mode="json") for item in decisions] == before_decisions
    assert [item.evaluation for item in again.candidates] == [item.evaluation for item in result.candidates]
    assert again.simulation_id == result.simulation_id
    assert live == before_live
    assert live.slots[0].shelf_quantity == 8
    assert live.slots[0].slot_id == "A02-S03"
    assert live.slots[0].backroom_quantity == 54
    assert CORRELATION_ID in caplog.text
    assert result.simulation_id in caplog.text
    assert "simulation scored" in caplog.text


def test_an_actionless_decision_keeps_the_evaluator_baseline() -> None:
    live = _live()
    before = copy.deepcopy(live)
    decision = _decision(proposed_actions=[])
    result = simulate([decision], live, evaluate=_kpi)

    oracle = _oracle(result.simulation_id, decision.decision_id, ())
    assert result.candidates[0].evaluation == oracle
    assert oracle["business_score"] == "-0.04"
    assert decision.simulation_id is None
    assert decision.expected_impact.kpi_score == UNSCORED_IMPACT
    assert live == before


def test_evaluator_exception_hides_the_cause(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    live = _live()
    before = copy.deepcopy(live)
    decision = _decision()

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        raise RuntimeError("secret")

    with pytest.raises(SimulationError) as caught:
        simulate([decision], live, evaluate=evaluate)

    assert caught.value.reason == EVALUATION_FAILED
    assert caught.value.correlation_id == CORRELATION_ID
    assert caught.value.__cause__ is None
    assert "secret" not in str(caught.value)
    assert "secret" not in caplog.text
    assert "RuntimeError" not in caplog.text
    assert decision.simulation_id is None
    assert decision.expected_impact.kpi_score == UNSCORED_IMPACT
    assert live == before


def test_an_occupied_destination_discards_every_candidate(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    live = _live(
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
    before = copy.deepcopy(live)
    decisions = _plan(_bundle(), _provider(_canonical()))
    calls: list[str] = []

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        calls.append(candidate_id)
        return _kpi(snapshot, candidate_id, actions)

    with pytest.raises(SimulationError) as caught:
        simulate(decisions, live, evaluate=evaluate)

    assert caught.value.reason == EVALUATION_FAILED
    assert caught.value.__cause__ is None
    assert "occupied" not in str(caught.value)
    assert "occupied" not in caplog.text
    assert "KpiError" not in caplog.text
    assert calls == [item.decision_id for item in decisions]
    assert all(item.simulation_id is None for item in decisions)
    assert all(item.expected_impact.kpi_score == UNSCORED_IMPACT for item in decisions)
    assert live == before
    assert live.slots[0].shelf_quantity == 8
    assert live.slots[0].backroom_quantity == 54


def test_one_bad_score_discards_the_earlier_candidate() -> None:
    live = _live()
    before = copy.deepcopy(live)
    first = _decision()
    second = _decision(
        decision_id=f"plan-{CORRELATION_ID}-P017-2",
        proposed_actions=[ChangeFacings(sku="P017", facings=4)],
    )
    calls: list[str] = []

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        calls.append(candidate_id)
        raw = dict(_kpi(snapshot, candidate_id, actions))
        if candidate_id.endswith("-2"):
            raw["formula_id"] = "other"
        return raw

    with pytest.raises(SimulationError) as caught:
        simulate([first, second], live, evaluate=evaluate)

    assert caught.value.reason == EVALUATION_FAILED
    assert calls == [first.decision_id, second.decision_id]
    assert first.simulation_id is None
    assert second.simulation_id is None
    assert live == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("formula_id", "other"),
        ("simulation_id", "sim-other"),
        ("candidate_id", "other"),
        ("correlation_id", "other"),
        ("business_score", True),
        ("business_score", 0.12),
        ("business_score", "nope"),
        ("business_score", "NaN"),
        ("business_score", None),
    ],
)
def test_a_result_that_is_not_this_simulation_is_rejected(field: str, value: object) -> None:
    live = _live()
    before = copy.deepcopy(live)

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        raw = dict(_kpi(snapshot, candidate_id, actions))
        raw[field] = value
        return raw

    with pytest.raises(SimulationError) as caught:
        simulate([_decision()], live, evaluate=evaluate)

    assert caught.value.reason == EVALUATION_FAILED
    assert live == before


def test_a_non_mapping_result_is_rejected() -> None:
    live = _live()

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        return ["nope"]  # type: ignore[return-value]

    with pytest.raises(SimulationError) as caught:
        simulate([_decision()], live, evaluate=evaluate)
    assert caught.value.reason == EVALUATION_FAILED


@pytest.mark.parametrize(
    "decisions",
    [
        pytest.param(
            [
                _decision(),
                _decision(decision_id=f"plan-{CORRELATION_ID}-P017-2", context_version="store-001:v9"),
            ],
            id="later-context",
        ),
        pytest.param([_decision(evidence=[])], id="empty-evidence"),
        pytest.param([_decision(evidence=[_bundle(store_id="store-002")])], id="other-store"),
        pytest.param(
            [_decision(evidence=[_bundle(correlation_id="run-other")])],
            id="other-correlation",
        ),
    ],
)
def test_context_mismatch_does_not_score(decisions: list[Decision]) -> None:
    live = _live()
    before = copy.deepcopy(live)
    calls: list[str] = []

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        calls.append(candidate_id)
        return _boom(snapshot, candidate_id, actions)

    with pytest.raises(SimulationError) as caught:
        simulate(decisions, live, evaluate=evaluate)

    assert caught.value.reason == CONTEXT_MISMATCH
    assert caught.value.correlation_id == CORRELATION_ID
    assert calls == []
    assert live == before
    assert all(item.simulation_id is None for item in decisions)


def test_an_unknown_action_is_rejected_before_evaluation() -> None:
    live = _live()
    good = _decision()
    raw = good.model_dump()
    bad = Decision.model_construct(
        decision_id=f"plan-{CORRELATION_ID}-P017-2",
        agent_id=good.agent_id,
        context_version=good.context_version,
        context_timestamp=good.context_timestamp,
        evidence=good.evidence,
        proposed_actions=["nope"],
        simulation_id=None,
        expected_impact=good.expected_impact,
    )
    calls: list[str] = []

    def evaluate(
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        calls.append(candidate_id)
        return _boom(snapshot, candidate_id, actions)

    with pytest.raises(SimulationError) as caught:
        simulate([good, bad], live, evaluate=evaluate)

    assert caught.value.reason == INVALID_REQUEST
    assert calls == []
    assert raw == good.model_dump()


@pytest.mark.parametrize(
    "decisions",
    [
        pytest.param([], id="empty"),
        pytest.param(None, id="missing"),
        pytest.param("not-a-list", id="text"),
        pytest.param(b"bytes", id="bytes"),
        pytest.param([{"decision_id": "plan-1"}], id="dict"),
        pytest.param([object()], id="object"),
        pytest.param([_decision(decision_id=" ")], id="blank-id"),
        pytest.param([_decision(), _decision()], id="duplicate-id"),
    ],
)
def test_invalid_request_does_not_score(decisions: object) -> None:
    live = _live()
    before = copy.deepcopy(live)
    with pytest.raises(SimulationError) as caught:
        simulate(decisions, live, evaluate=_boom)  # type: ignore[arg-type]
    assert caught.value.reason == INVALID_REQUEST
    assert caught.value.correlation_id == CORRELATION_ID
    assert live == before


@pytest.mark.parametrize(
    ("live", "correlation_id"),
    [
        pytest.param(object(), "unknown", id="not-a-view"),
        pytest.param(_live(correlation_id="  "), "unknown", id="blank-correlation"),
        pytest.param(_live(correlation_id=None), "unknown", id="missing-correlation"),
        pytest.param(_live(store_id=" "), CORRELATION_ID, id="blank-store"),
        pytest.param(_live(context_version=""), CORRELATION_ID, id="blank-context"),
        pytest.param(_live(observed_at=datetime(2026, 10, 10, 8, 0)), CORRELATION_ID, id="naive-clock"),
        pytest.param(_live(observed_at="2026-10-10T08:00:00Z"), CORRELATION_ID, id="text-clock"),
        pytest.param(
            _live(observed_at=datetime(2026, 10, 10, 8, 0, tzinfo=_NoOffset())),
            CORRELATION_ID,
            id="clock-without-offset",
        ),
        pytest.param(_live(slots=()), CORRELATION_ID, id="no-slots"),
        pytest.param(_live(slots=[]), CORRELATION_ID, id="slot-list"),
        pytest.param(_live(slots=None), CORRELATION_ID, id="missing-slots"),
        pytest.param(_live(slots=("nope",)), CORRELATION_ID, id="slot-type"),
        pytest.param(_live(slots=(_slot(sku=" "),)), CORRELATION_ID, id="blank-sku"),
        pytest.param(_live(slots=(_slot(slot_id=""),)), CORRELATION_ID, id="blank-slot"),
        pytest.param(
            _live(slots=(_slot(), _slot(sku="P018", slot_id="A02-S03"))),
            CORRELATION_ID,
            id="duplicate-slot",
        ),
        pytest.param(
            _live(slots=(_slot(), _slot(sku="P017", slot_id="B01-S01"))),
            CORRELATION_ID,
            id="duplicate-sku",
        ),
        pytest.param(_live(slots=(_slot(shelf_quantity=True),)), CORRELATION_ID, id="bool-quantity"),
        pytest.param(_live(slots=(_slot(shelf_quantity=-1),)), CORRELATION_ID, id="negative-shelf"),
        pytest.param(_live(slots=(_slot(shelf_quantity=8.0),)), CORRELATION_ID, id="float-shelf"),
        pytest.param(_live(slots=(_slot(backroom_quantity="54"),)), CORRELATION_ID, id="text-backroom"),
        pytest.param(_live(slots=(_slot(facings=0),)), CORRELATION_ID, id="zero-facings"),
        pytest.param(
            _live(slots=(_slot(sales_velocity_units_per_hour="fast"),)),
            CORRELATION_ID,
            id="bad-velocity",
        ),
        pytest.param(
            _live(slots=(_slot(sales_velocity_units_per_hour=""),)),
            CORRELATION_ID,
            id="blank-velocity",
        ),
        pytest.param(_live(slots=(_slot(price="-1"),)), CORRELATION_ID, id="negative-price"),
    ],
)
def test_invalid_snapshot_does_not_score(live: object, correlation_id: str) -> None:
    with pytest.raises(SimulationError) as caught:
        simulate([], live, evaluate=_boom)  # type: ignore[arg-type]
    assert caught.value.reason == INVALID_SNAPSHOT
    assert caught.value.correlation_id == correlation_id


def test_simulator_source_does_not_score_or_call_a_model() -> None:
    source = Path(simulate.__code__.co_filename).read_text(encoding="utf-8").lower()
    assert "openai" not in source
    assert "vertex" not in source
    assert "google.cloud" not in source
    assert "firestore" not in source
    assert "evaluate_candidate" not in source
    assert "services.simulation" not in source
    assert "services.forecasting" not in source
    assert "submit_action_for_commit" not in source
    assert "0.12" not in source
    assert "0.09" not in source
    assert "0.07" not in source
    assert "b02-s01" not in source
