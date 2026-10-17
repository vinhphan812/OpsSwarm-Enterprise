"""Investigator evidence: versioned tool results, never guessed quantities."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_FORECAST_ROOT = Path(__file__).resolve().parents[3] / "services" / "forecasting"
if str(_FORECAST_ROOT) not in sys.path:
    sys.path.insert(0, str(_FORECAST_ROOT))

from demand.forecast import ForecastInputs, SaleObservation, forecast_demand

from retailtwin_api.agents.investigator.evidence import (
    ENTITY_MISMATCH,
    MANDATORY_SOURCES,
    MISSING_VERSION,
    NOT_REQUESTED,
    SALES_HISTORY_UNAVAILABLE,
    InvestigatorError,
    bind_read_port,
    investigate,
)
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.tool_registry import (
    LIVE_WRITE_TOOLS,
    SOURCE_UNAVAILABLE,
    ToolRegistry,
    build_store_registry,
)
from retailtwin_api.contracts import EvidenceBundle, EvidenceItem, ToolCapability
from retailtwin_api.demand_surge import reset_weekend_demand_surge
from retailtwin_api.llm.contracts import LlmProvider, LlmRequest, LlmResponse, LlmToolCall
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.schemas import ProductInventory, StoreEvent, StoreResponse

SERIES = reset_weekend_demand_surge()
TRIGGER = SERIES[-1]
COLLECTED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
CORRELATION_ID = "run-weekend-demand-surge-1"
PLANOGRAM = {
    "version": "1",
    "observed_at": COLLECTED_AT.isoformat(),
    "placements": [
        {
            "sku": "P017",
            "shelf_id": "A02",
            "slot_id": "A02-S03",
            "facings": 2,
        }
    ],
}


class MemoryStore:
    def __init__(self, products: list[ProductInventory]) -> None:
        self.products = products
        self._view = StoreResponse(
            store_id=products[0].store_id,
            context_version="store-001:v1",
            version="1",
            products=list(products),
        )

    def inventory(self, sku: str) -> ProductInventory | None:
        for product in self.products:
            if product.sku == sku:
                return product
        return None

    def view(self) -> StoreResponse:
        return self._view


class RaisingProvider(LlmProvider):
    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise RuntimeError("secret")


def _p017() -> ProductInventory:
    return ProductInventory(
        store_id="store-001",
        sku="P017",
        shelf_id="A02",
        slot_id="A02-S03",
        facings=2,
        shelf_quantity=8,
        backroom_quantity=54,
        version=1,
    )


def _p099() -> ProductInventory:
    return ProductInventory(
        store_id="store-001",
        sku="P099",
        shelf_id="B02",
        slot_id="B02-S01",
        facings=1,
        shelf_quantity=999,
        backroom_quantity=999,
        version=7,
    )


def _start() -> InvestigationStart:
    return InvestigationStart(
        investigation_id=f"inv-{TRIGGER.event_id}",
        event=TRIGGER,
    )


def _sales_observations() -> list[SaleObservation]:
    return [
        SaleObservation(
            event_id=event.event_id,
            store_id=event.store_id,
            sku=event.sku,
            quantity=event.quantity,
            occurred_at=event.occurred_at,
            correlation_id=event.correlation_id,
        )
        for event in SERIES
        if event.sku == "P017"
    ]


def _expected_forecast() -> dict[str, object]:
    return forecast_demand(
        ForecastInputs(
            store_id=TRIGGER.store_id,
            sku="P017",
            correlation_id=CORRELATION_ID,
            generated_at=COLLECTED_AT,
            sales=_sales_observations(),
            horizon_hours=Decimal(4),
            use_ml=False,
        )
    ).as_dict()


def _read_sales(args: Any) -> dict[str, Any]:
    matched = [event for event in SERIES if event.sku == args.sku]
    latest = max(event.occurred_at for event in matched)
    window = timedelta(hours=args.window_hours)
    selected = [
        event
        for event in matched
        if latest - window <= event.occurred_at <= latest
    ]
    return {
        "version": selected[-1].event_id,
        "sku": args.sku,
        "observed_at": latest.isoformat(),
        "sales": [
            {
                "event_id": event.event_id,
                "quantity": event.quantity,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in selected
        ],
    }


def _read_forecast(args: Any) -> dict[str, Any]:
    sales = [item for item in _sales_observations() if item.sku == args.sku]
    result = forecast_demand(
        ForecastInputs(
            store_id=sales[0].store_id,
            sku=args.sku,
            correlation_id=sales[0].correlation_id,
            generated_at=COLLECTED_AT,
            sales=sales,
            horizon_hours=Decimal(args.horizon_hours),
            use_ml=False,
        )
    ).as_dict()
    result["version"] = result["formula_id"]
    result["observed_at"] = result["generated_at"]
    return result


def _read_promotions(args: Any) -> dict[str, Any]:
    # No promotions fixture exists. The port reports that empty observation.
    return {
        "version": "0",
        "sku": args.sku,
        "observed_at": COLLECTED_AT.isoformat(),
        "promotions": [],
    }


def _read_planogram(_args: Any) -> dict[str, Any]:
    return copy.deepcopy(PLANOGRAM)


def _registry(
    store: MemoryStore,
    *,
    promotions: bool = True,
    planogram: Any = _read_planogram,
    sales_history: Any | None = _read_sales,
) -> ToolRegistry:
    registry = build_store_registry(store)
    if sales_history is not None:
        if sales_history is _read_sales:
            bind_read_port(registry, "get_sales_history", sales_history)
        else:
            registry.bind_catalog_tool("get_sales_history", sales_history)
    bind_read_port(registry, "forecast_demand", _read_forecast)
    if promotions:
        bind_read_port(registry, "get_promotions", _read_promotions)
    if planogram is not None:
        if planogram is _read_planogram:
            bind_read_port(registry, "get_planogram", planogram)
        else:
            registry.bind_catalog_tool("get_planogram", planogram)
    return registry


def _calls() -> list[LlmToolCall]:
    return [
        LlmToolCall(id="inv", name="get_inventory", arguments={"sku": "P017"}),
        LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": "A02"}),
        LlmToolCall(
            id="sales",
            name="get_sales_history",
            arguments={"sku": "P017", "window_hours": 4},
        ),
        LlmToolCall(
            id="forecast",
            name="forecast_demand",
            arguments={"sku": "P017", "horizon_hours": 4},
        ),
        LlmToolCall(id="promo", name="get_promotions", arguments={"sku": "P017"}),
        LlmToolCall(id="plan", name="get_planogram", arguments={}),
        LlmToolCall(
            id="stock",
            name="get_stockout_risk",
            arguments={"sku": "P017", "horizon_hours": 4},
        ),
        LlmToolCall(
            id="move",
            name="move_product",
            arguments={"sku": "P017", "from_slot": "A02-S03", "to_slot": "B02-S01"},
        ),
        LlmToolCall(
            id="write",
            name="update_inventory",
            arguments={"sku": "P017", "shelf_quantity": 0},
        ),
    ]


def _provider(
    calls: list[LlmToolCall],
    content: str | None = None,
) -> FakeLlmProvider:
    return FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                content=content,
                tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop",
            )
        ]
    )


def _snapshot(store: MemoryStore) -> dict[str, Any]:
    return store.view().model_dump()


def _run(
    registry: ToolRegistry,
    calls: list[LlmToolCall],
    *,
    store: MemoryStore,
    content: str | None = None,
    provider: LlmProvider | None = None,
) -> tuple[EvidenceBundle, LlmProvider, dict[str, Any], dict[str, Any]]:
    chosen = provider or _provider(calls, content)
    before = _snapshot(store)
    bundle = asyncio.run(
        investigate(
            _start(),
            provider=chosen,
            registry=registry,
            collected_at=COLLECTED_AT,
        )
    )
    return bundle, chosen, before, _snapshot(store)


def _source(bundle: EvidenceBundle, source: str) -> EvidenceItem:
    found = [item for item in bundle.items if item.payload.get("source") == source]
    assert len(found) == 1
    return found[0]


def _sources(bundle: EvidenceBundle) -> list[str]:
    return [str(item.payload["source"]) for item in bundle.items]


def test_p017_bundle_uses_store_sales_and_forecast_service(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    store = MemoryStore([_p017()])
    registry = _registry(store)
    bundle, provider, before, after = _run(registry, _calls(), store=store)
    expected = _expected_forecast()
    product = store.inventory("P017")
    assert product is not None

    assert bundle.bundle_id == f"bundle-{CORRELATION_ID}-P017"
    assert bundle.provenance == "tool-registry"
    assert bundle.source == "investigator"
    assert bundle.store_id == "store-001"
    assert bundle.correlation_id == CORRELATION_ID
    assert bundle.collected_at == COLLECTED_AT
    assert bundle.freshness == COLLECTED_AT
    assert bundle.is_sufficient is True
    assert bundle.entity_versions == {"P017": "1"}
    assert bundle.source_versions == {
        "sales_history": "evt-p017-surge-0008",
        "forecast": "forecast-demand-v1",
    }
    assert _sources(bundle) == [source for source, _tool in MANDATORY_SOURCES]
    assert not hasattr(_start(), "prompt")
    assert "prompt" not in bundle.model_dump()

    inventory = _source(bundle, "inventory")
    assert inventory.event_type == "inventory"
    assert inventory.payload["entity_id"] == "P017"
    assert inventory.payload["version"] == "1"
    assert inventory.payload["observed_at"] == COLLECTED_AT.isoformat()
    assert inventory.payload["value"]["shelf_quantity"] == product.shelf_quantity
    assert inventory.payload["value"]["backroom_quantity"] == product.backroom_quantity
    assert inventory.payload["value"]["slot_id"] == product.slot_id
    assert inventory.payload["value"]["facings"] == product.facings

    shelf = _source(bundle, "shelf")
    assert shelf.payload["entity_id"] == "A02"
    assert shelf.payload["version"] == "1"
    assert shelf.payload["value"]["products"][0]["sku"] == "P017"
    assert shelf.payload["value"]["products"][0]["shelf_quantity"] == product.shelf_quantity

    latest = max(event.occurred_at for event in SERIES)
    window = timedelta(hours=4)
    expected_units = sum(
        event.quantity
        for event in SERIES
        if latest - window <= event.occurred_at <= latest
    )
    sales = _source(bundle, "sales_history")
    assert sum(item["quantity"] for item in sales.payload["value"]["sales"]) == expected_units
    assert expected_units == 73
    assert sales.payload["version"] == "evt-p017-surge-0008"

    forecast = _source(bundle, "forecast")
    for key, item in expected.items():
        assert forecast.payload["value"][key] == item
    assert forecast.payload["value"]["forecast_units"] == "73"
    assert forecast.payload["version"] == "forecast-demand-v1"
    assert forecast.payload["observed_at"] == expected["generated_at"]

    promotions = _source(bundle, "promotions")
    assert promotions.payload["value"]["promotions"] == []
    assert promotions.payload["version"] == "0"

    planogram = _source(bundle, "planogram")
    assert planogram.payload["entity_id"] == "store-001"
    assert planogram.payload["value"] == PLANOGRAM
    assert "backroom_quantity" not in planogram.payload["value"]
    assert "insufficient_evidence" not in {item.event_type for item in bundle.items}
    assert "get_stockout_risk" not in json.dumps(bundle.model_dump(mode="json"))
    assert "move_product" not in json.dumps(bundle.model_dump(mode="json"))
    assert "update_inventory" not in json.dumps(bundle.model_dump(mode="json"))

    assert isinstance(provider, FakeLlmProvider)
    sent = provider.call_history[0]
    offered = {tool.name for tool in sent.tools}
    assert "get_inventory" in offered
    assert "get_promotions" in offered
    assert "move_product" not in offered
    assert "update_inventory" not in offered
    assert LIVE_WRITE_TOOLS.isdisjoint(offered)
    assert sent.model == "investigator"
    assert json.loads(sent.messages[1].content or "") == {
        "correlation_id": CORRELATION_ID,
        "event_id": TRIGGER.event_id,
        "sku": "P017",
        "store_id": "store-001",
    }
    assert registry.activity.simulation_actions == []
    assert registry.activity.simulations == []
    assert registry.activity.commit_requests == []
    assert before == after
    assert "evidence collected" in caplog.text
    assert CORRELATION_ID in caplog.text
    assert "is_sufficient=True" in caplog.text


def test_same_inputs_and_clock_return_the_same_bundle() -> None:
    store = MemoryStore([_p017()])
    registry = _registry(store)
    first, _, before, _ = _run(registry, _calls(), store=store)
    second, _, _, after = _run(registry, _calls(), store=store)
    assert first.bundle_id == second.bundle_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert before == after


def test_removed_promotions_port_is_insufficient_and_not_guessed() -> None:
    store = MemoryStore([_p017()])
    registry = _registry(store, promotions=False)
    bundle, _, before, after = _run(registry, _calls(), store=store)
    promotions = _source(bundle, "promotions")
    assert bundle.is_sufficient is False
    assert promotions.event_type == "insufficient_evidence"
    assert promotions.payload == {
        "source": "promotions",
        "entity_id": "P017",
        "reason": "unknown_tool",
    }
    assert "value" not in promotions.payload
    kept = [
        item.event_type
        for item in bundle.items
        if item.event_type != "insufficient_evidence"
    ]
    assert kept == ["inventory", "shelf", "sales_history", "forecast", "planogram"]
    assert before == after


def test_model_prose_does_not_become_inventory(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    store = MemoryStore([_p017()])
    registry = _registry(store)
    bundle, _, _, _ = _run(
        registry,
        _calls(),
        store=store,
        content="shelf_quantity is 999",
    )
    inventory = _source(bundle, "inventory")
    encoded = json.dumps(bundle.model_dump(mode="json"))
    assert inventory.payload["value"]["shelf_quantity"] == store.inventory("P017").shelf_quantity
    assert "999" not in encoded
    assert "999" not in caplog.text


def test_content_without_tool_calls_marks_every_source_missing() -> None:
    store = MemoryStore([_p017()])
    registry = _registry(store)
    bundle, _, before, after = _run(
        registry,
        [],
        store=store,
        content="shelf_quantity is 8 and forecast_units is 73",
    )
    assert bundle.is_sufficient is False
    assert len(bundle.items) == 6
    assert bundle.entity_versions == {}
    for source, _tool in MANDATORY_SOURCES:
        item = _source(bundle, source)
        assert item.event_type == "insufficient_evidence"
        assert item.payload["reason"] == NOT_REQUESTED
        assert "value" not in item.payload
    assert _source(bundle, "planogram").payload["entity_id"] == "store-001"
    encoded = json.dumps(bundle.model_dump(mode="json"))
    assert "73" not in encoded
    assert before == after


def test_provider_failure_raises_without_the_secret_or_a_bundle() -> None:
    store = MemoryStore([_p017()])
    registry = _registry(store)
    before = _snapshot(store)
    with pytest.raises(InvestigatorError) as caught:
        asyncio.run(
            investigate(
                _start(),
                provider=RaisingProvider(),
                registry=registry,
                collected_at=COLLECTED_AT,
            )
        )
    assert str(caught.value) == f"Evidence collection failed for {CORRELATION_ID}."
    assert caught.value.correlation_id == CORRELATION_ID
    assert "secret" not in str(caught.value)
    assert _snapshot(store) == before


def test_write_tools_are_not_evidence_and_do_not_change_the_store() -> None:
    store = MemoryStore([_p017()])
    registry = _registry(store)
    bundle, _, before, after = _run(registry, _calls(), store=store)
    assert bundle.is_sufficient is True
    assert registry.activity.simulation_actions == []
    assert before == after
    assert store.inventory("P017").shelf_quantity == 8
    assert store.inventory("P017").backroom_quantity == 54


def test_other_sku_quantities_are_not_p017_evidence() -> None:
    store = MemoryStore([_p017(), _p099()])
    registry = _registry(store)
    calls = _calls()
    calls[0] = LlmToolCall(id="inv", name="get_inventory", arguments={"sku": "P099"})
    calls[1] = LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": "B02"})
    bundle, _, before, after = _run(registry, calls, store=store)
    inventory = _source(bundle, "inventory")
    shelf = _source(bundle, "shelf")
    assert bundle.is_sufficient is False
    assert bundle.entity_versions == {}
    assert bundle.source_versions == {
        "sales_history": "evt-p017-surge-0008",
        "forecast": "forecast-demand-v1",
    }
    assert inventory.payload == {
        "source": "inventory",
        "entity_id": "P017",
        "reason": ENTITY_MISMATCH,
    }
    assert shelf.payload["reason"] == ENTITY_MISMATCH
    assert shelf.payload["entity_id"] == "B02"
    assert "value" not in inventory.payload
    assert "value" not in shelf.payload
    assert "999" not in json.dumps(bundle.model_dump(mode="json"))
    assert before == after


def test_output_for_another_sku_is_dropped_when_the_argument_matches() -> None:
    registry = ToolRegistry()

    def lying(_args: Any) -> dict[str, Any]:
        return {"sku": "P099", "version": 4, "shelf_quantity": 999}

    registry.bind_catalog_tool("get_inventory", lying)
    calls = [LlmToolCall(id="inv", name="get_inventory", arguments={"sku": "P017"})]
    store = MemoryStore([_p017()])
    bundle, _, _, _ = _run(registry, calls, store=store)
    inventory = _source(bundle, "inventory")
    assert inventory.payload["reason"] == ENTITY_MISMATCH
    assert "value" not in inventory.payload
    assert "999" not in json.dumps(bundle.model_dump(mode="json"))


def test_missing_shelf_keeps_the_requested_id_and_no_value() -> None:
    store = MemoryStore([_p017()])
    registry = _registry(store)
    calls = _calls()
    calls[1] = LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": "Z99"})
    bundle, _, before, after = _run(registry, calls, store=store)
    shelf = _source(bundle, "shelf")
    assert bundle.is_sufficient is False
    assert shelf.payload == {
        "source": "shelf",
        "entity_id": "Z99",
        "reason": "not_found",
    }
    assert _source(bundle, "inventory").event_type == "inventory"
    assert before == after


def test_planogram_without_a_version_drops_the_numbers() -> None:
    store = MemoryStore([_p017()])

    def unversioned(_args: Any) -> dict[str, Any]:
        return {"placements": [{"sku": "P017", "facings": 2}], "shelf_quantity": 8}

    registry = _registry(store, planogram=unversioned)
    bundle, _, _, _ = _run(registry, _calls(), store=store)
    planogram = _source(bundle, "planogram")
    assert bundle.is_sufficient is False
    assert planogram.payload == {
        "source": "planogram",
        "entity_id": "store-001",
        "reason": MISSING_VERSION,
    }
    assert "shelf_quantity" not in planogram.payload
    assert _source(bundle, "inventory").event_type == "inventory"


def test_last_successful_read_survives_a_later_failure() -> None:
    registry = ToolRegistry()
    seen = {"n": 0}

    def read_sales(args: Any) -> dict[str, Any]:
        seen["n"] += 1
        return {"version": str(seen["n"]), "sku": args.sku, "units": seen["n"]}

    bind_read_port(registry, "get_sales_history", read_sales)
    calls = [
        LlmToolCall(
            id="1",
            name="get_sales_history",
            arguments={"sku": "P017", "window_hours": 4},
        ),
        LlmToolCall(
            id="2",
            name="get_sales_history",
            arguments={"sku": "P017", "window_hours": 4},
        ),
        LlmToolCall(id="3", name="get_sales_history", arguments={}),
    ]
    bundle, _, _, _ = _run(registry, calls, store=MemoryStore([_p017()]))
    sales = _source(bundle, "sales_history")
    assert sales.event_type == "sales_history"
    assert sales.payload["version"] == "2"
    assert sales.payload["value"]["units"] == 2
    assert seen["n"] == 2


def test_bind_read_port_hides_source_failures() -> None:
    registry = ToolRegistry()
    bind_read_port(registry, "get_promotions", lambda _args: None)
    missing = registry.invoke(
        "get_promotions",
        {"sku": "P017"},
        granted={ToolCapability.READ},
        correlation_id=CORRELATION_ID,
    )
    assert missing.ok is False
    assert missing.error_code == SOURCE_UNAVAILABLE
    assert missing.message == "The source failed."

    def boom(_args: Any) -> dict[str, Any]:
        raise RuntimeError("secret token")

    failing = ToolRegistry()
    bind_read_port(failing, "get_promotions", boom)
    raised = failing.invoke(
        "get_promotions",
        {"sku": "P017"},
        granted={ToolCapability.READ},
    )
    assert raised.error_code == SOURCE_UNAVAILABLE
    assert raised.message == "The source failed."
    assert "secret" not in (raised.message or "")

    bare = ToolRegistry()
    bind_read_port(bare, "get_promotions", lambda _args: {"promotions": []})
    without_version = bare.invoke(
        "get_promotions",
        {"sku": "P017"},
        granted={ToolCapability.READ},
    )
    assert without_version.error_code == SOURCE_UNAVAILABLE

    ready = ToolRegistry()
    bind_read_port(
        ready,
        "get_promotions",
        lambda args: {"version": "0", "sku": args.sku, "promotions": []},
    )
    found = ready.invoke(
        "get_promotions",
        {"sku": "P017"},
        granted={ToolCapability.READ},
    )
    assert found.ok is True
    assert found.output == {"version": "0", "sku": "P017", "promotions": []}


def test_investigator_source_does_not_import_a_model_sdk_or_forecast_package() -> None:
    source = Path(investigate.__code__.co_filename).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "openai" not in lowered
    assert "vertex" not in lowered
    assert "firestore" not in lowered
    assert "google.cloud" not in lowered
    assert "demand.forecast" not in lowered
    assert "services.forecasting" not in lowered
    assert TRIGGER.sku == "P017"
    assert all(event.correlation_id == CORRELATION_ID for event in SERIES)


# ─── issue #215 — BigQuery sales_history wiring ──────────────────────────────


class TestInvestigatorBigQuerySalesHistory:
    """Issue #215: BigQuery-backed ``get_sales_history`` is a real READ port.

    The canonical investigator must accept a Pydantic-typed mapping
    from the BigQuery reader, surface ``sales_history_unavailable``
    when the reader returns ``None`` or raises, and never invent a
    number when BigQuery is empty.
    """

    def test_fake_bigquery_with_p017_rows_round_trips_into_evidence_bundle(self) -> None:
        from retailtwin_api.bigquery_sales_history import read_sales_history
        from retailtwin_api.contracts import EvidenceBundle
        from tests.test_bigquery_sales_history import FakeBigQueryClient

        store = MemoryStore([_p017()])
        registry = _registry(store, sales_history=None)
        clear_sales = registry.invoke(
            "get_sales_history",
            {"sku": "P017", "window_hours": 4},
            granted={ToolCapability.READ},
        )
        assert clear_sales.ok is False

        saturday_landed = datetime(2026, 10, 10, 11, 55, 0, tzinfo=timezone.utc)
        rows = [
            _FakeRowSimpleNamespace(
                event_id=f"evt-sat-{i}",
                correlation_id=CORRELATION_ID,
                store_id="store-001",
                sku="P017",
                quantity=4,
                occurred_at=COLLECTED_AT,
                landed_at=saturday_landed,
            )
            for i in range(20)
        ]
        client = FakeBigQueryClient(row_factory=lambda q: rows)

        def sales_history_port(args: Any) -> dict[str, Any] | None:
            payload = read_sales_history(
                args,
                client=client,
                job_config=None,
                store_id="store-001",
                now=COLLECTED_AT,
            )
            return payload

        bind_read_port(registry, "get_sales_history", sales_history_port)
        bundle, _, _, _ = _run(registry, _calls(), store=store)
        assert isinstance(bundle, EvidenceBundle)
        assert bundle.is_sufficient is True
        # Issue #215 / PR #253 fix: ``version`` is now a deterministic
        # provenance digest (window + watermark + lineage), so the
        # bundle's ``source_versions[sales_history]`` is the digest
        # — the BigQuery job id (kept for debugging) lives in
        # ``value.query_job_id``.
        sales = _source(bundle, "sales_history")
        assert sales.event_type == "sales_history"
        version = bundle.source_versions["sales_history"]
        assert version.startswith("sales-evidence-")
        assert sales.payload["version"] == version
        assert sales.payload["value"]["query_job_id"] == "bq-job-test"
        # The new provenance tuple is round-tripped into the payload
        # so downstream consumers (Planner, Simulator, audit) can
        # see the exact snapshot the candidate was scored against.
        assert sales.payload["value"]["query_window"] == [
            (COLLECTED_AT - timedelta(hours=4)).astimezone(timezone.utc).isoformat(),
            COLLECTED_AT.astimezone(timezone.utc).isoformat(),
        ]
        assert sales.payload["value"]["source_watermark"] == saturday_landed.astimezone(timezone.utc).isoformat()
        assert sales.payload["value"]["data_lineage"] == [
            "retailtwin-ai-511002",
            "retailtwin",
            "sales_events",
        ]
        # ``content_digest`` is a deterministic sha256 over the row
        # contents (issue #215 / PR #253 review 2).
        assert isinstance(sales.payload["value"]["content_digest"], str)
        assert len(sales.payload["value"]["content_digest"]) == 64
        # The BigQuery reader payload is copied under ``value``; the
        # canonical fields ``sku`` / ``window_hours`` / ``total_quantity``
        # are visible there.
        assert sales.payload["value"]["sku"] == "P017"
        assert sales.payload["value"]["window_hours"] == 4
        # 20 rows × 4 units = 80 units sold in the canonical 4h window.
        assert sales.payload["value"]["row_count"] == 20
        assert sales.payload["value"]["total_quantity"] == 80
        # Inventory version still keys ``entity_versions`` by SKU.
        assert bundle.entity_versions == {"P017": "1"}

    def test_empty_bigquery_surfaces_sales_history_unavailable(self) -> None:
        from retailtwin_api.bigquery_sales_history import read_sales_history
        from tests.test_bigquery_sales_history import FakeBigQueryClient

        store = MemoryStore([_p017()])
        registry = _registry(store, sales_history=None)
        client = FakeBigQueryClient(row_factory=lambda q: [])

        def empty_bq_sales_history(args: Any) -> dict[str, Any] | None:
            return read_sales_history(
                args,
                client=client,
                job_config=None,
                store_id="store-001",
                now=COLLECTED_AT,
            )

        bind_read_port(registry, "get_sales_history", empty_bq_sales_history)
        bundle, _, _, _ = _run(registry, _calls(), store=store)
        # No fabricated number: the BigQuery reader returned ``None`` and
        # ``bind_read_port`` raised ``source_unavailable``; the bundle
        # surfaces that as ``sales_history_unavailable``.
        sales = _source(bundle, "sales_history")
        assert sales.event_type == "insufficient_evidence"
        assert sales.payload == {
            "source": "sales_history",
            "entity_id": "P017",
            "reason": SALES_HISTORY_UNAVAILABLE,
        }
        assert "value" not in sales.payload
        assert bundle.is_sufficient == False
        # The investigator never invents a quantity on the sales_history
        # item: the canonical 80-unit Saturday surge and the 4h-window
        # total must not appear in the sales_history payload (the
        # ``forecast`` payload legitimately carries its own value).
        sales_payload = json.dumps(sales.payload)
        assert "80" not in sales_payload
        assert "total_quantity" not in sales_payload

    def test_bigquery_error_surfaces_sales_history_unavailable(self) -> None:
        from retailtwin_api.bigquery_sales_history import read_sales_history
        from tests.test_bigquery_sales_history import FakeBigQueryClient

        store = MemoryStore([_p017()])
        registry = _registry(store, sales_history=None)
        client = FakeBigQueryClient(raise_on_query=RuntimeError("secret-bq"))

        def broken_bq_sales_history(args: Any) -> dict[str, Any] | None:
            return read_sales_history(
                args,
                client=client,
                job_config=None,
                store_id="store-001",
                now=COLLECTED_AT,
            )

        bind_read_port(registry, "get_sales_history", broken_bq_sales_history)
        bundle, _, _, _ = _run(registry, _calls(), store=store)
        sales = _source(bundle, "sales_history")
        assert sales.event_type == "insufficient_evidence"
        assert sales.payload["reason"] == SALES_HISTORY_UNAVAILABLE
        assert "secret-bq" not in json.dumps(bundle.model_dump(mode="json"))

    def test_run_id_is_deterministic_across_investigations(self) -> None:
        from retailtwin_api.bigquery_sales_history import read_sales_history
        from tests.test_bigquery_sales_history import FakeBigQueryClient

        store = MemoryStore([_p017()])
        registry = _registry(store, sales_history=None)
        rows = [
            _FakeRowSimpleNamespace(
                event_id=f"evt-sat-{i}",
                correlation_id=CORRELATION_ID,
                store_id="store-001",
                sku="P017",
                quantity=4,
                occurred_at=COLLECTED_AT,
            )
            for i in range(20)
        ]
        client = FakeBigQueryClient(row_factory=lambda q: rows)

        def stable_bq_sales_history(args: Any) -> dict[str, Any] | None:
            return read_sales_history(
                args,
                client=client,
                job_config=None,
                store_id="store-001",
                now=COLLECTED_AT,
            )

        bind_read_port(registry, "get_sales_history", stable_bq_sales_history)
        first, _, _, _ = _run(registry, _calls(), store=store)
        second, _, _, _ = _run(registry, _calls(), store=store)
        assert first.bundle_id == second.bundle_id
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.source_versions == second.source_versions
        # Two calls, two queries against the fake client (the reader is
        # stateless). The bundle is identical so no duplication leaks
        # into the investigator's evidence state.
        assert len(client.calls) == 2


class _FakeRowSimpleNamespace:
    """A BigQuery row that mimics ``google.cloud.bigquery.Row`` attribute access."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
