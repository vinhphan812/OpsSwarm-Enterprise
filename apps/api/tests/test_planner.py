"""Planner: structured candidates bound to evidence, never a guessed KPI."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from retailtwin_api.agents.planner.plans import (
    FORBIDDEN_ACTION,
    INSUFFICIENT_EVIDENCE,
    INVALID_CONTEXT,
    INVALID_OUTPUT,
    PROVIDER_FAILED,
    UNSCORED_IMPACT,
    PlannerError,
    plan,
)
from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    EvidenceBundle,
    EvidenceItem,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.llm.contracts import LlmProvider, LlmRequest, LlmResponse, LlmToolCall
from retailtwin_api.llm.fake import FakeLlmProvider

CORRELATION_ID = "run-weekend-demand-surge-1"
CONTEXT_VERSION = "store-001:v1"
COLLECTED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
CONTEXT_AT = datetime(2026, 10, 10, 12, 5, tzinfo=timezone.utc)


class RaisingProvider(LlmProvider):
    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise RuntimeError("secret")


def _bundle(
    *,
    sufficient: bool = True,
    backroom: int = 54,
    slot_id: str = "A02-S03",
) -> EvidenceBundle:
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
                "slot_id": slot_id,
                "facings": 2,
                "shelf_quantity": 8,
                "backroom_quantity": backroom,
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
    return EvidenceBundle(
        bundle_id=f"bundle-{CORRELATION_ID}-P017",
        provenance="tool-registry",
        source="investigator",
        entity_versions={"P017": "1"} if sufficient else {},
        collected_at=COLLECTED_AT,
        freshness=COLLECTED_AT,
        store_id="store-001",
        correlation_id=CORRELATION_ID,
        is_sufficient=sufficient,
        items=[inventory, forecast] if sufficient else [inventory],
    )


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


def _provider(body: dict[str, Any] | str, *, tool_call: bool = False) -> FakeLlmProvider:
    content = body if isinstance(body, str) else json.dumps(body)
    calls = []
    if tool_call:
        calls.append(
            LlmToolCall(id="write", name="update_inventory", arguments={"sku": "P017", "secret": "secret"})
        )
    return FakeLlmProvider(
        responses=[FakeLlmProvider.Response(content=content, tool_calls=calls, finish_reason="stop")]
    )


def _plan(
    bundle: EvidenceBundle,
    provider: LlmProvider,
    *,
    context_version: str = CONTEXT_VERSION,
    context_timestamp: datetime = CONTEXT_AT,
) -> list[Decision]:
    return asyncio.run(
        plan(
            bundle,
            provider=provider,
            context_version=context_version,
            context_timestamp=context_timestamp,
        )
    )


def test_demand_surge_evidence_becomes_three_bound_decisions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    bundle = _bundle()
    provider = _provider(_canonical(), tool_call=True)
    decisions = _plan(bundle, provider)
    again = _plan(bundle, _provider(_canonical()))

    assert [item.decision_id for item in decisions] == [
        f"plan-{CORRELATION_ID}-P017-1",
        f"plan-{CORRELATION_ID}-P017-2",
        f"plan-{CORRELATION_ID}-P017-3",
    ]
    assert [item.model_dump(mode="json") for item in decisions] == [
        item.model_dump(mode="json") for item in again
    ]
    assert all(item.agent_id == "retailtwin-planner" for item in decisions)
    assert all(item.context_version == CONTEXT_VERSION for item in decisions)
    assert all(item.context_timestamp == CONTEXT_AT for item in decisions)
    assert all(item.simulation_id is None for item in decisions)
    assert all(item.evidence == [bundle] for item in decisions)
    assert all(item.expected_impact.kpi_score == UNSCORED_IMPACT for item in decisions)
    assert UNSCORED_IMPACT == -1.0
    assert [item.expected_impact.description for item in decisions] == [
        "Replenish P017 from the backroom.",
        "Increase facings, then replenish P017.",
        "Move P017, increase facings, then replenish.",
    ]
    assert decisions[0].proposed_actions == [ReplenishShelf(sku="P017", quantity=12)]
    assert decisions[1].proposed_actions == [
        ChangeFacings(sku="P017", facings=4),
        ReplenishShelf(sku="P017", quantity=12),
    ]
    assert decisions[2].proposed_actions == [
        MoveProduct(sku="P017", from_slot="A02-S03", to_slot="B02-S01"),
        ChangeFacings(sku="P017", facings=4),
        ReplenishShelf(sku="P017", quantity=12),
    ]
    sent = provider.call_history[0]
    assert sent.model == "planner"
    assert sent.tools == []
    assert sent.tool_choice is not None and sent.tool_choice.mode == "none"
    assert sent.structured_output is not None
    assert sent.structured_output.name == "candidate_plans"
    encoded_schema = json.dumps(sent.structured_output.json_schema)
    assert "$ref" not in encoded_schema
    assert "move_product" in encoded_schema
    assert "change_facings" in encoded_schema
    assert "replenish_shelf" in encoded_schema
    assert "update_inventory" not in encoded_schema
    assert "kpi_score" not in encoded_schema
    facts = json.loads(sent.messages[1].content or "")
    assert facts["sku"] == "P017"
    assert facts["slot_id"] == "A02-S03"
    assert facts["backroom_quantity"] == 54
    assert facts["forecast_units"] == "73"
    assert "context_version" not in facts
    assert "prompt" not in facts
    assert CORRELATION_ID in caplog.text
    assert "plans created" in caplog.text
    assert "secret" not in caplog.text


def test_replenishing_the_whole_backroom_is_allowed() -> None:
    body = {
        "candidates": [
            {
                "reason": "Move the full backroom onto the shelf.",
                "actions": [{"type": "replenish_shelf", "sku": "P017", "quantity": 54}],
            },
            {
                "reason": "Move one unit onto the shelf.",
                "actions": [{"type": "replenish_shelf", "sku": "P017", "quantity": 1}],
            },
        ]
    }
    decisions = _plan(_bundle(), _provider(body))
    assert [item.proposed_actions[0] for item in decisions] == [
        ReplenishShelf(sku="P017", quantity=54),
        ReplenishShelf(sku="P017", quantity=1),
    ]


def test_unknown_action_is_rejected_before_simulation(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    body = _canonical()
    body["candidates"][0]["actions"] = [
        {"type": "update_inventory", "sku": "P017", "note": "secret"}
    ]
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == INVALID_OUTPUT
    assert str(caught.value) == f"Planning failed for {CORRELATION_ID}."
    assert "secret" not in str(caught.value)
    assert "secret" not in caplog.text


def test_same_slot_move_is_forbidden() -> None:
    body = _canonical()
    body["candidates"][2]["actions"][0]["to_slot"] = "A02-S03"
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == FORBIDDEN_ACTION


def test_move_from_an_unobserved_slot_is_forbidden() -> None:
    body = _canonical()
    body["candidates"][2]["actions"][0]["from_slot"] = "A01-S01"
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == FORBIDDEN_ACTION


def test_action_for_another_sku_is_forbidden() -> None:
    body = _canonical()
    body["candidates"][0]["actions"][0]["sku"] = "P099"
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == FORBIDDEN_ACTION


def test_replenishment_above_the_backroom_is_forbidden() -> None:
    body = _canonical()
    body["candidates"][0]["actions"][0]["quantity"] = 55
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == FORBIDDEN_ACTION


def test_model_kpi_is_not_accepted() -> None:
    body = _canonical()
    body["candidates"][0]["kpi_score"] = 0.99
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == INVALID_OUTPUT
    assert "0.99" not in str(caught.value)


def test_one_candidate_is_invalid_output() -> None:
    body = {"candidates": [_canonical()["candidates"][0]]}
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == INVALID_OUTPUT


def test_prose_is_invalid_output() -> None:
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider("Replenish twelve units."))
    assert caught.value.reason == INVALID_OUTPUT


def test_blank_reason_is_invalid_output() -> None:
    body = _canonical()
    body["candidates"][0]["reason"] = "   "
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), _provider(body))
    assert caught.value.reason == INVALID_OUTPUT


def test_insufficient_evidence_does_not_call_the_provider() -> None:
    provider = _provider(_canonical())
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(sufficient=False), provider)
    assert caught.value.reason == INSUFFICIENT_EVIDENCE
    assert provider.call_count == 0


def test_naive_context_timestamp_is_rejected_before_the_provider() -> None:
    provider = _provider(_canonical())
    with pytest.raises(PlannerError) as caught:
        _plan(
            _bundle(),
            provider,
            context_timestamp=datetime(2026, 10, 10, 12, 5),
        )
    assert caught.value.reason == INVALID_CONTEXT
    assert provider.call_count == 0


def test_provider_failure_hides_the_secret() -> None:
    with pytest.raises(PlannerError) as caught:
        _plan(_bundle(), RaisingProvider())
    assert caught.value.reason == PROVIDER_FAILED
    assert caught.value.correlation_id == CORRELATION_ID
    assert "secret" not in str(caught.value)


def test_planner_source_does_not_import_a_model_sdk_or_the_kpi_package() -> None:
    source = Path(plan.__code__.co_filename).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "openai" not in lowered
    assert "vertex" not in lowered
    assert "firestore" not in lowered
    assert "google.cloud" not in lowered
    assert "evaluate_candidate" not in lowered
    assert "services.simulation" not in lowered
    assert "services.forecasting" not in lowered
