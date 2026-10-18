"""Planner: deterministic, rule-based decisioning for production + local runs.

The planner ships a deterministic path as its default so the chain no
longer depends on a model being reachable. These tests pin the rule
set end-to-end so the production chain's ``plan`` stage stays
reproducible across runs and across CI / dev environments.

The historical LLM path is preserved behind ``PLANNER_USE_LLM``; the
existing ``test_planner.py`` suite keeps covering that path via the
``os.environ.setdefault`` in ``conftest.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from retailtwin_api.agents.planner.plans import (
    NO_ACTIONABLE_DECISION,
    PLANNER_USE_LLM_ENV,
    UNSCORED_IMPACT,
    PlannerError,
    _llm_enabled,
    _observed,
    plan,
    plan_decision_deterministic,
)
from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    EvidenceBundle,
    EvidenceItem,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.llm.contracts import LlmProvider, LlmRequest, LlmResponse
from retailtwin_api.llm.fake import FakeLlmProvider

CORRELATION_ID = "run-weekend-demand-surge-1"
CONTEXT_VERSION = "store-001:v1"
COLLECTED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
CONTEXT_AT = datetime(2026, 10, 10, 12, 5, tzinfo=timezone.utc)


# ─── helpers ────────────────────────────────────────────────────────────────


def _inventory_item(
    *,
    sku: str = "P017",
    slot_id: str = "A02-S03",
    shelf_id: str = "A02",
    shelf_quantity: int = 8,
    backroom_quantity: int = 54,
    facings: int = 2,
    version: str = "1",
) -> EvidenceItem:
    return EvidenceItem(
        event_type="inventory",
        payload={
            "source": "inventory",
            "entity_id": sku,
            "version": version,
            "observed_at": COLLECTED_AT.isoformat(),
            "value": {
                "store_id": "store-001",
                "sku": sku,
                "shelf_id": shelf_id,
                "slot_id": slot_id,
                "facings": facings,
                "shelf_quantity": shelf_quantity,
                "backroom_quantity": backroom_quantity,
                "version": int(version),
            },
        },
    )


def _sales_history_item(
    *,
    sku: str = "P017",
    window_hours: int = 4,
    sales: list[dict[str, Any]] | None = None,
) -> EvidenceItem:
    if sales is None:
        sales = [
            {"event_id": "evt-1", "quantity": 30, "occurred_at": COLLECTED_AT.isoformat()},
            {"event_id": "evt-2", "quantity": 43, "occurred_at": COLLECTED_AT.isoformat()},
        ]
    return EvidenceItem(
        event_type="sales_history",
        payload={
            "source": "sales_history",
            "entity_id": sku,
            "version": "sales-history-v1",
            "observed_at": COLLECTED_AT.isoformat(),
            "value": {
                "version": "sales-history-v1",
                "sku": sku,
                "window_hours": window_hours,
                "sales": sales,
            },
        },
    )


def _forecast_item(
    *,
    sku: str = "P017",
    forecast_units: str = "73",
    horizon_hours: int = 4,
) -> EvidenceItem:
    return EvidenceItem(
        event_type="forecast",
        payload={
            "source": "forecast",
            "entity_id": sku,
            "version": "forecast-demand-v1",
            "observed_at": COLLECTED_AT.isoformat(),
            "value": {
                "forecast_units": forecast_units,
                "formula_id": "forecast-demand-v1",
                "horizon_hours": horizon_hours,
                "sku": sku,
            },
        },
    )


def _bundle(
    *,
    sufficient: bool = True,
    shelf_quantity: int = 8,
    backroom_quantity: int = 54,
    facings: int = 2,
    sales: list[dict[str, Any]] | None = None,
    forecast_units: str = "73",
    slot_id: str = "A02-S03",
) -> EvidenceBundle:
    items: list[EvidenceItem] = [
        _inventory_item(
            shelf_quantity=shelf_quantity,
            backroom_quantity=backroom_quantity,
            facings=facings,
            slot_id=slot_id,
        )
    ]
    if sufficient:
        items.append(_sales_history_item(sales=sales))
        items.append(_forecast_item(forecast_units=forecast_units))
    return EvidenceBundle(
        bundle_id=f"bundle-{CORRELATION_ID}-P017",
        provenance="tool-registry",
        source="investigator",
        entity_versions={"P017": "1"} if sufficient else {},
        source_versions={
            "sales_history": "sales-history-v1",
            "forecast": "forecast-demand-v1",
        } if sufficient else {},
        collected_at=COLLECTED_AT,
        freshness=COLLECTED_AT,
        store_id="store-001",
        correlation_id=CORRELATION_ID,
        is_sufficient=sufficient,
        items=items,
    )


class _RaisingProvider(LlmProvider):
    """Provider whose ``complete`` call raises if invoked."""

    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise AssertionError(
            "provider.complete MUST NOT be called in deterministic mode"
        )


def _plan(
    bundle: EvidenceBundle,
    *,
    provider: LlmProvider | None = None,
    context_version: str = CONTEXT_VERSION,
    context_timestamp: datetime = CONTEXT_AT,
) -> list[Decision]:
    return asyncio.run(
        plan(
            bundle,
            provider=provider or _RaisingProvider(),
            context_version=context_version,
            context_timestamp=context_timestamp,
        )
    )


# ─── feature flag ──────────────────────────────────────────────────────────


def test_llm_enabled_default_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    assert _llm_enabled() is False


def test_llm_enabled_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "yes", "on", "TRUE", " True "):
        monkeypatch.setenv(PLANNER_USE_LLM_ENV, value)
        assert _llm_enabled() is True, value


def test_llm_enabled_falsy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv(PLANNER_USE_LLM_ENV, value)
        assert _llm_enabled() is False, value


# ─── rule-based plan() end-to-end (PLANNER_USE_LLM unset / OFF) ───────────


def test_planner_decision_chooses_replenish_for_high_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    # 73 units in 4 hours = 18.25 units/hour > REPLENISH threshold (6).
    bundle = _bundle(backroom_quantity=54, shelf_quantity=8, facings=2)
    decisions = _plan(bundle)
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.agent_id == "retailtwin-planner"
    assert decision.context_version == CONTEXT_VERSION
    assert decision.context_timestamp == CONTEXT_AT
    assert decision.evidence == [bundle]
    assert decision.simulation_id is None
    assert decision.expected_impact.kpi_score == UNSCORED_IMPACT
    assert len(decision.proposed_actions) == 1
    action = decision.proposed_actions[0]
    assert isinstance(action, ReplenishShelf)
    assert action.sku == "P017"
    assert action.quantity == 20  # min(backroom=54, REPLENISH_MAX_UNITS=20)
    assert decision.decision_id == f"plan-{CORRELATION_ID}-P017-1"
    assert "deterministic" in decision.expected_impact.description


def test_planner_decision_chooses_change_facings_for_sustained_high_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    # Shelf fully stocked, backroom empty, but sustained velocity 18 units/h
    # crosses the CHANGE_FACINGS threshold (12). facings=2 -> 3.
    bundle = _bundle(
        backroom_quantity=0,
        shelf_quantity=20,
        facings=2,
    )
    decisions = _plan(bundle)
    assert len(decisions) == 1
    action = decisions[0].proposed_actions[0]
    assert isinstance(action, ChangeFacings)
    assert action.sku == "P017"
    assert action.facings == 3


def test_planner_decision_chooses_minimal_replenish_for_empty_shelf_with_stock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    # velocity low (no sales), shelf=0, backroom>0 -> minimal touch-up.
    bundle = _bundle(
        backroom_quantity=10,
        shelf_quantity=0,
        sales=[],
        forecast_units="0",
    )
    decisions = _plan(bundle)
    assert len(decisions) == 1
    action = decisions[0].proposed_actions[0]
    assert isinstance(action, ReplenishShelf)
    assert action.sku == "P017"
    assert action.quantity == 1


def test_planner_decision_no_actionable_decision_when_no_stock_and_no_demand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    # shelf=0, backroom=0, velocity=0 -> deterministic returns []; plan()
    # raises PlannerError(NO_ACTIONABLE_DECISION).
    bundle = _bundle(
        backroom_quantity=0,
        shelf_quantity=0,
        sales=[],
        forecast_units="0",
    )
    with pytest.raises(PlannerError) as caught:
        _plan(bundle)
    assert caught.value.reason == NO_ACTIONABLE_DECISION
    assert caught.value.correlation_id == CORRELATION_ID


def test_planner_deterministic_does_not_call_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    bundle = _bundle()
    provider = _RaisingProvider()
    # The provider MUST NOT be invoked. If the deterministic path
    # accidentally delegates to the LLM, _RaisingProvider.complete
    # will trip the assertion embedded in the raise.
    decisions = _plan(bundle, provider=provider)
    assert len(decisions) == 1


def test_planner_deterministic_uses_forecast_when_sales_history_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    # sales_history is empty (velocity from sales = 0), but the forecast
    # says 200 units / 4h = 50 units/h — well above the
    # CHANGE_FACINGS threshold. Shelf is already full and backroom is
    # empty so the ReplenishShelf rule does NOT fire; the planner falls
    # through to ChangeFacings, driven by the forecast-derived velocity.
    bundle = _bundle(
        sales=[],
        forecast_units="200",
        shelf_quantity=20,
        backroom_quantity=0,
        facings=2,
    )
    decisions = _plan(bundle)
    action = decisions[0].proposed_actions[0]
    assert isinstance(action, ChangeFacings)
    assert action.facings == 3


def test_planner_deterministic_replenish_caps_at_backroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    # backroom < REPLENISH_MAX_UNITS -> quantity == backroom.
    bundle = _bundle(backroom_quantity=10, shelf_quantity=4, facings=1)
    decisions = _plan(bundle)
    action = decisions[0].proposed_actions[0]
    assert isinstance(action, ReplenishShelf)
    assert action.quantity == 10


# ─── plan_decision_deterministic direct call ──────────────────────────────


def test_plan_decision_deterministic_returns_one_bound_decision() -> None:
    bundle = _bundle()
    observed = _observed(bundle)
    decisions = plan_decision_deterministic(
        bundle,
        observed=observed,
        context_version=CONTEXT_VERSION,
        context_timestamp=CONTEXT_AT,
    )
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.context_version == CONTEXT_VERSION
    assert decision.context_timestamp == CONTEXT_AT
    assert decision.evidence == [bundle]
    assert decision.simulation_id is None
    assert decision.expected_impact.kpi_score == UNSCORED_IMPACT
    assert UNSCORED_IMPACT == -1.0


def test_plan_decision_deterministic_decision_shape_matches_existing_contract() -> None:
    """The deterministic Decision must remain a valid Decision for downstream code."""
    bundle = _bundle()
    observed = _observed(bundle)
    [decision] = plan_decision_deterministic(
        bundle,
        observed=observed,
        context_version=CONTEXT_VERSION,
        context_timestamp=CONTEXT_AT,
    )
    # Decision is the contracts.Decision pydantic model.
    assert isinstance(decision, Decision)
    # Each proposed action is one of the three frozen action models.
    for action in decision.proposed_actions:
        assert isinstance(action, (MoveProduct, ChangeFacings, ReplenishShelf))


def test_plan_decision_deterministic_logs_no_actionable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    bundle = _bundle(backroom_quantity=0, shelf_quantity=0, sales=[], forecast_units="0")
    observed = _observed(bundle)
    decisions = plan_decision_deterministic(
        bundle,
        observed=observed,
        context_version=CONTEXT_VERSION,
        context_timestamp=CONTEXT_AT,
    )
    assert decisions == []
    assert "no_actionable_decision" in caplog.text


# ─── decision ID / shape stability ─────────────────────────────────────────


def test_planner_deterministic_decision_id_is_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    bundle = _bundle()
    first = _plan(bundle)
    again = _plan(bundle)
    assert [d.decision_id for d in first] == [d.decision_id for d in again]
    assert first[0].decision_id == f"plan-{CORRELATION_ID}-P017-1"


def test_planner_deterministic_full_dump_is_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    bundle = _bundle()
    first = _plan(bundle)
    again = _plan(bundle)
    assert [d.model_dump(mode="json") for d in first] == [
        d.model_dump(mode="json") for d in again
    ]


def test_planner_deterministic_carries_bundle_in_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    bundle = _bundle()
    [decision] = _plan(bundle)
    assert decision.evidence == [bundle]


def test_planner_deterministic_proposed_actions_use_frozen_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    # High velocity + stock available -> ReplenishShelf.
    bundle = _bundle(backroom_quantity=54, shelf_quantity=8, facings=2)
    [decision] = _plan(bundle)
    assert len(decision.proposed_actions) >= 1
    for action in decision.proposed_actions:
        # Only the three frozen action models are allowed downstream.
        assert type(action) in {MoveProduct, ChangeFacings, ReplenishShelf}


# ─── insulators ───────────────────────────────────────────────────────────


def test_planner_deterministic_rejects_naive_context_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    bundle = _bundle()
    with pytest.raises(PlannerError) as caught:
        _plan(bundle, context_timestamp=datetime(2026, 10, 10, 12, 5))
    assert caught.value.reason == "invalid_context"


def test_planner_deterministic_rejects_insufficient_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(PLANNER_USE_LLM_ENV, raising=False)
    bundle = _bundle(sufficient=False)
    with pytest.raises(PlannerError) as caught:
        _plan(bundle)
    assert caught.value.reason == "insufficient_evidence"


# ─── LLM path still works when explicitly enabled ──────────────────────────


def test_planner_llm_path_is_used_when_env_flag_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PLANNER_USE_LLM_ENV, "true")
    canonical = {
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
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(content=json.dumps(canonical), finish_reason="stop")
        ]
    )
    decisions = _plan(_bundle(), provider=provider)
    assert len(decisions) == 3
    assert all(d.context_version == CONTEXT_VERSION for d in decisions)


def test_planner_source_does_not_import_model_sdk_or_kpi_package() -> None:
    """Even with the deterministic path, the planner source must not
    import a model SDK or the simulation / forecasting package
    directly — the rule-based logic lives entirely inside the module.
    """
    source = Path(plan.__code__.co_filename).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "openai" not in lowered
    assert "vertex" not in lowered
    assert "firestore" not in lowered
    assert "google.cloud" not in lowered
    assert "evaluate_candidate" not in lowered
    assert "services.simulation" not in lowered
    assert "services.forecasting" not in lowered