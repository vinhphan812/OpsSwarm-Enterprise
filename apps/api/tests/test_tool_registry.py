"""Allow-listed tool registry: one schema, three capabilities, no live write."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from retailtwin_api.agents.orchestrator.tool_registry import (
    CATALOG,
    EXPOSED_TOOL_NAMES,
    HANDLER_FAILED,
    INVALID_ARGUMENTS,
    LIVE_WRITE_FORBIDDEN,
    LIVE_WRITE_TOOLS,
    NOT_FOUND,
    PERMISSION_DENIED,
    SOURCE_UNAVAILABLE,
    TIMEOUT,
    UNKNOWN_TOOL,
    ToolFailure,
    ToolRegistry,
    ToolRegistryError,
    build_store_registry,
)
from retailtwin_api.contracts import (
    Decision,
    EvidenceBundle,
    EvidenceItem,
    ExpectedImpact,
    MoveProduct,
    ToolCapability,
)
from retailtwin_api.llm.contracts import LlmMessage, LlmRequest, LlmToolCall, ToolChoicePolicy
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.llm.openai_compatible import _convert_tools_openai
from retailtwin_api.llm.vertex import _convert_tools_vertex
from retailtwin_api.settings import DEFAULT_FIXTURE
from retailtwin_api.store import open_store

READ = {ToolCapability.READ}
SIMULATION = {ToolCapability.SIMULATION}
COMMIT = {ToolCapability.COMMIT_REQUEST}
ALL = {ToolCapability.READ, ToolCapability.SIMULATION, ToolCapability.COMMIT_REQUEST}


@pytest.fixture
def store():
    return open_store(DEFAULT_FIXTURE, "store-001")


@pytest.fixture
def registry(store):
    return build_store_registry(store)


def _snapshot(store) -> dict[str, object]:
    item = store.inventory("P001")
    assert item is not None
    return item.model_dump()


def _decision() -> dict[str, object]:
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    decision = Decision(
        decision_id="d-11",
        agent_id="retailtwin-orchestrator",
        context_version="store-001:v1",
        context_timestamp=now,
        evidence=[
            EvidenceBundle(
                bundle_id="b1",
                provenance="fixture",
                source="store",
                entity_versions={"P001": "1"},
                collected_at=now,
                freshness=now,
                store_id="store-001",
                correlation_id="run-11",
                is_sufficient=True,
                items=[EvidenceItem(event_type="inventory", payload={"sku": "P001"})],
            )
        ],
        proposed_actions=[MoveProduct(sku="P001", from_slot="A01-S01", to_slot="A02-S01")],
        simulation_id="sim-1",
        expected_impact=ExpectedImpact(kpi_score=0.5, description="test"),
    )
    return decision.model_dump(mode="json")


def test_catalog_covers_the_mvp_names_and_hides_unbound_tools(registry) -> None:
    assert {
        "get_inventory",
        "get_store_state",
        "get_shelf_state",
        "get_backroom_inventory",
        "get_sales_history",
        "get_sales_velocity",
        "forecast_demand",
        "get_stockout_risk",
        "get_product_performance",
        "get_promotions",
        "get_planogram",
        "move_product",
        "change_facings",
        "replenish_shelf",
        "create_simulation",
        "compare_scenarios",
        "calculate_business_impact",
        "submit_action_for_commit",
    } <= set(CATALOG)
    exposed = {tool.name for tool in registry.llm_tools()}
    assert exposed == EXPOSED_TOOL_NAMES
    assert "forecast_demand" not in exposed
    assert "get_promotions" not in exposed
    assert "compare_scenarios" not in exposed
    assert LIVE_WRITE_TOOLS.isdisjoint(exposed)


def test_one_schema_is_translated_for_openai_and_vertex(registry) -> None:
    tools = registry.llm_tools()
    openai = _convert_tools_openai(tools)
    vertex = _convert_tools_vertex(tools)
    openai_names = [item["function"]["name"] for item in openai]
    vertex_names = [item["name"] for item in vertex]
    assert openai_names == vertex_names == [tool.name for tool in tools]
    openai_inventory = next(item for item in openai if item["function"]["name"] == "get_inventory")
    vertex_inventory = next(item for item in vertex if item["name"] == "get_inventory")
    assert openai_inventory["function"]["parameters"] == vertex_inventory["parameters"]
    assert openai_inventory["function"]["parameters"]["required"] == ["sku"]
    assert openai_inventory["function"]["parameters"]["additionalProperties"] is False
    submit = next(tool for tool in tools if tool.name == "submit_action_for_commit")
    encoded = json.dumps(submit.parameters)
    assert "$ref" not in encoded
    assert "decision_id" in encoded
    policy = ToolChoicePolicy(mode="tool_choice", name="get_inventory")
    policy.validate_for_request(tools)


def test_fake_model_reads_p001_without_a_second_tool_definition(registry, store) -> None:
    tools = registry.llm_tools(capabilities=READ)
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                tool_calls=[
                    LlmToolCall(id="call-1", name="get_inventory", arguments={"sku": "P001"})
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    request = LlmRequest(
        model="fake-model",
        messages=[LlmMessage(role="user", content="Read P001")],
        tools=tools,
        tool_choice=ToolChoicePolicy(mode="required_tool", name="get_inventory"),
    )
    response = asyncio.run(provider.complete(request))
    assert [tool.name for tool in provider.call_history[0].tools] == [tool.name for tool in tools]
    results = registry.execute_tool_calls(
        response.tool_calls,
        granted=READ,
        correlation_id="run-11",
    )
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].correlation_id == "run-11"
    assert results[0].output == _snapshot(store)
    assert results[0].output == {
        "store_id": "store-001",
        "sku": "P001",
        "shelf_id": "A01",
        "slot_id": "A01-S01",
        "facings": 3,
        "shelf_quantity": 8,
        "backroom_quantity": 42,
        "version": 1,
    }


def test_store_reads_match_the_fixture(registry, store) -> None:
    state = registry.invoke("get_store_state", None, granted=READ, correlation_id="run-11")
    assert state.ok is True
    assert state.output == store.view().model_dump()
    shelf = registry.invoke("get_shelf_state", {"shelf_id": "A01"}, granted=READ)
    assert shelf.output == {
        "shelf_id": "A01",
        "products": [_snapshot(store)],
    }
    backroom = registry.invoke("get_backroom_inventory", {"sku": "P001"}, granted=READ)
    assert backroom.output == {
        "store_id": "store-001",
        "sku": "P001",
        "backroom_quantity": 42,
        "version": 1,
    }


def test_missing_sku_and_shelf_are_not_found(registry) -> None:
    missing = registry.invoke("get_inventory", {"sku": "P999"}, granted=READ)
    assert missing.ok is False
    assert missing.error_code == NOT_FOUND
    assert missing.output is None
    shelf = registry.invoke("get_shelf_state", {"shelf_id": "Z99"}, granted=READ)
    assert shelf.error_code == NOT_FOUND
    backroom = registry.invoke("get_backroom_inventory", {"sku": "P999"}, granted=READ)
    assert backroom.error_code == NOT_FOUND


def test_invalid_payloads_are_rejected(registry) -> None:
    missing = registry.invoke("get_inventory", {}, granted=READ)
    extra = registry.invoke("get_inventory", {"sku": "P001", "shelf_quantity": 0}, granted=READ)
    facings = registry.invoke("change_facings", {"sku": "P001", "facings": 0}, granted=SIMULATION)
    arguments = registry.invoke("get_inventory", ["P001"], granted=READ)
    assert missing.error_code == INVALID_ARGUMENTS
    assert extra.error_code == INVALID_ARGUMENTS
    assert facings.error_code == INVALID_ARGUMENTS
    assert arguments.error_code == INVALID_ARGUMENTS
    assert registry.activity.simulation_actions == []


def test_permission_class_is_fail_closed(registry) -> None:
    move = registry.invoke(
        "move_product",
        {"sku": "P001", "from_slot": "A01-S01", "to_slot": "A02-S01"},
        granted=READ,
        correlation_id="run-11",
    )
    submit = registry.invoke(
        "submit_action_for_commit",
        {"decision": _decision()},
        granted=SIMULATION,
    )
    read = registry.invoke("get_inventory", {"sku": "P001"}, granted=COMMIT)
    denied = registry.invoke("get_inventory", {"sku": "P001"}, granted=set())
    assert move.error_code == PERMISSION_DENIED
    assert move.capability is ToolCapability.SIMULATION
    assert move.correlation_id == "run-11"
    assert submit.error_code == PERMISSION_DENIED
    assert read.error_code == PERMISSION_DENIED
    assert denied.error_code == PERMISSION_DENIED
    assert registry.activity.simulation_actions == []
    assert registry.activity.commit_requests == []


def test_simulation_and_commit_do_not_change_the_store(registry, store) -> None:
    before = _snapshot(store)
    created = registry.invoke("create_simulation", {}, granted=SIMULATION)
    moved = registry.invoke(
        "move_product",
        {"sku": "P001", "from_slot": "A01-S01", "to_slot": "A02-S01"},
        granted=SIMULATION,
    )
    facings = registry.invoke(
        "change_facings",
        {"sku": "P001", "facings": 4},
        granted=SIMULATION,
    )
    replenished = registry.invoke(
        "replenish_shelf",
        {"sku": "P001", "quantity": 6},
        granted=SIMULATION,
    )
    pinned = registry.invoke(
        "create_simulation",
        {"context_version": "store-001:v9"},
        granted=SIMULATION,
    )
    submitted = registry.invoke(
        "submit_action_for_commit",
        {"decision": _decision()},
        granted=COMMIT,
    )
    assert created.output == {
        "simulation_id": "sim-1",
        "context_version": "store-001:v1",
        "status": "created",
    }
    assert pinned.output["simulation_id"] == "sim-2"
    assert pinned.output["context_version"] == "store-001:v9"
    assert moved.output["status"] == "accepted"
    assert facings.output["action"] == {"sku": "P001", "facings": 4}
    assert replenished.output["action"] == {"sku": "P001", "quantity": 6}
    assert submitted.output == {
        "status": "commit_requested",
        "decision_id": "d-11",
        "context_version": "store-001:v1",
        "action_count": 1,
    }
    assert "expiry" not in submitted.output
    assert len(registry.activity.simulation_actions) == 3
    assert registry.activity.commit_requests[0]["decision_id"] == "d-11"
    assert _snapshot(store) == before
    assert store.view().context_version == "store-001:v1"


@pytest.mark.parametrize("name", ["update_inventory", "write_firestore", "Update_Inventory"])
def test_live_write_primitives_are_forbidden(registry, store, name: str) -> None:
    before = _snapshot(store)
    result = registry.invoke(
        name,
        {"sku": "P001", "shelf_quantity": 0},
        granted=ALL,
    )
    assert result.error_code == LIVE_WRITE_FORBIDDEN
    assert result.ok is False
    assert _snapshot(store) == before


def test_unknown_tool_is_rejected(registry) -> None:
    result = registry.invoke("get_weather", {}, granted=ALL)
    blank = registry.invoke("", {}, granted=ALL)
    assert result.error_code == UNKNOWN_TOOL
    assert blank.error_code == UNKNOWN_TOOL


def test_timeout_and_handler_failures_stay_controlled(registry) -> None:
    class ProbeArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def slow(_args: Any) -> dict[str, Any]:
        import time

        time.sleep(0.3)
        return {}

    def boom(_args: Any) -> dict[str, Any]:
        raise RuntimeError("path /secret/key")

    def wrong_shape(_args: Any) -> Any:
        return ["not", "an", "object"]

    def not_json(_args: Any) -> dict[str, Any]:
        return {"when": datetime.now(timezone.utc)}

    def unavailable(_args: Any) -> dict[str, Any]:
        raise ToolFailure(SOURCE_UNAVAILABLE, "No sales source is bound.")

    registry.register(
        name="slow_probe",
        description="Waits.",
        capability=ToolCapability.READ,
        args_model=ProbeArgs,
        handler=slow,
        timeout_s=0.05,
    )
    registry.register(
        name="boom_probe",
        description="Fails.",
        capability=ToolCapability.READ,
        args_model=ProbeArgs,
        handler=boom,
    )
    registry.register(
        name="shape_probe",
        description="Returns a list.",
        capability=ToolCapability.READ,
        args_model=ProbeArgs,
        handler=wrong_shape,
    )
    registry.register(
        name="clock_probe",
        description="Returns a datetime.",
        capability=ToolCapability.READ,
        args_model=ProbeArgs,
        handler=not_json,
    )
    timed = registry.invoke("slow_probe", {}, granted=READ)
    failed = registry.invoke("boom_probe", {}, granted=READ)
    shaped = registry.invoke("shape_probe", {}, granted=READ)
    clock = registry.invoke("clock_probe", {}, granted=READ)
    registry.bind_catalog_tool("forecast_demand", unavailable)
    unbound = registry.invoke(
        "forecast_demand",
        {"sku": "P017", "horizon_hours": 4},
        granted=READ,
    )
    assert timed.error_code == TIMEOUT
    assert failed.error_code == HANDLER_FAILED
    assert failed.message == "The tool failed."
    assert "secret" not in (failed.message or "")
    assert shaped.error_code == HANDLER_FAILED
    assert clock.error_code == HANDLER_FAILED
    assert unbound.error_code == SOURCE_UNAVAILABLE
    assert unbound.message == "No sales source is bound."
    assert "forecast_demand" in {tool.name for tool in registry.llm_tools()}


def test_bound_forecast_returns_the_port_value_unchanged(registry) -> None:
    def forecast(args: Any) -> dict[str, int | str]:
        return {"sku": args.sku, "horizon_hours": args.horizon_hours, "units": 73}

    registry.bind_catalog_tool("forecast_demand", forecast)
    result = registry.invoke(
        "forecast_demand",
        {"sku": "P017", "horizon_hours": 4},
        granted=READ,
    )
    assert result.output == {"sku": "P017", "horizon_hours": 4, "units": 73}
    invalid = registry.invoke(
        "forecast_demand",
        {"sku": "P017", "horizon_hours": 0},
        granted=READ,
    )
    assert invalid.error_code == INVALID_ARGUMENTS


def test_capability_filter_and_registration_guards(registry) -> None:
    commit_only = {tool.name for tool in registry.llm_tools(capabilities=COMMIT)}
    assert commit_only == {"submit_action_for_commit"}
    assert registry.llm_tools(capabilities=set()) == []

    class ProbeArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    def handler(_args: Any) -> dict[str, str]:
        return {"ok": "yes"}

    with pytest.raises(ToolRegistryError, match="live-write"):
        registry.register(
            name="update_inventory",
            description="no",
            capability=ToolCapability.READ,
            args_model=ProbeArgs,
            handler=handler,
        )
    with pytest.raises(ToolRegistryError, match="already registered"):
        registry.bind_catalog_tool("get_inventory", handler)
    with pytest.raises(ToolRegistryError, match="not in the tool catalog"):
        registry.bind_catalog_tool("get_weather", handler)
    with pytest.raises(ToolRegistryError, match="lower_snake"):
        registry.register(
            name="GetInventory",
            description="no",
            capability=ToolCapability.READ,
            args_model=ProbeArgs,
            handler=handler,
        )
    with pytest.raises(ToolRegistryError, match="timeout_s"):
        registry.register(
            name="zero_probe",
            description="no",
            capability=ToolCapability.READ,
            args_model=ProbeArgs,
            handler=handler,
            timeout_s=0,
        )
    with pytest.raises(ToolRegistryError, match="pydantic"):
        registry.register(
            name="bad_model",
            description="no",
            capability=ToolCapability.READ,
            args_model=object,  # type: ignore[arg-type]
            handler=handler,
        )
    with pytest.raises(ToolRegistryError, match="timeout_s"):
        registry.invoke("get_inventory", {"sku": "P001"}, granted=READ, timeout_s=0)
    with pytest.raises(ToolRegistryError, match="collection"):
        registry.invoke("get_inventory", {"sku": "P001"}, granted=ToolCapability.READ)  # type: ignore[arg-type]


def test_invalid_decision_does_not_record_a_commit(registry) -> None:
    result = registry.invoke(
        "submit_action_for_commit",
        {"decision": {"decision_id": "d-11"}},
        granted=COMMIT,
    )
    assert result.error_code == INVALID_ARGUMENTS
    assert registry.activity.commit_requests == []


def test_non_string_tool_name_is_unknown() -> None:
    registry = ToolRegistry()
    result = registry.invoke(None, {}, granted=ALL)  # type: ignore[arg-type]
    assert result.error_code == UNKNOWN_TOOL
    assert result.name == ""
