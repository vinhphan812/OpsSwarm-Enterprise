"""Investigator evidence: deterministic read path covers all 6 mandatory ports.

The investigator's deterministic path drives the six mandatory read ports
(``MANDATORY_SOURCES``) directly — NOT the LLM's tool-choice output. The
LLM is preserved as an optional synthesis step that may summarize or
annotate observations; its absence (or failure) does not invalidate the
bundle.

These tests verify the deterministic contract:

1. All six reads run even when the LLM is unavailable / returns no tool calls.
2. The per-SKU reads (``get_inventory``, ``get_sales_history``,
   ``forecast_demand``, ``get_promotions``) are called with the event's SKU.
3. The bundle is only ``is_sufficient=True`` when all six hits succeed.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

_FORECAST_ROOT = Path(__file__).resolve().parents[3] / "services" / "forecasting"
if str(_FORECAST_ROOT) not in sys.path:
    sys.path.insert(0, str(_FORECAST_ROOT))

from demand.forecast import ForecastInputs, SaleObservation, forecast_demand

from retailtwin_api.agents.investigator.evidence import (
    MANDATORY_SOURCES,
    InvestigatorError,
    bind_read_port,
    investigate,
)
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.tool_registry import (
    NOT_FOUND,
    SOURCE_UNAVAILABLE,
    ToolFailure,
    ToolRegistry,
    build_store_registry,
)
from retailtwin_api.demand_surge import reset_weekend_demand_surge
from retailtwin_api.llm.contracts import LlmProvider, LlmRequest, LlmResponse
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


class _MemoryStore:
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


class _RaisingProvider(LlmProvider):
    """Provider whose ``complete`` call raises unconditionally."""

    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise RuntimeError("llm unavailable — deterministic path must still produce a bundle")


class _EmptyToolCallProvider(LlmProvider):
    """Provider that returns no tool calls (mimics Vertex Gemini auto-mode)."""

    def __init__(self) -> None:
        self.call_count = 0
        self.last_request: LlmRequest | None = None

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.call_count += 1
        self.last_request = request
        return LlmResponse(
            id="empty-1",
            model=request.model,
            content=None,
            finish_reason="stop",
            tool_calls=[],
        )


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


def _read_sales(args: Any) -> dict[str, Any]:
    matched = [event for event in SERIES if event.sku == args.sku]
    latest = max(event.occurred_at for event in matched)
    from datetime import timedelta
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
    return {
        "version": "0",
        "sku": args.sku,
        "observed_at": COLLECTED_AT.isoformat(),
        "promotions": [],
    }


def _read_planogram(_args: Any) -> dict[str, Any]:
    import copy as _copy
    return _copy.deepcopy(PLANOGRAM)


def _registry(
    store: _MemoryStore,
    *,
    promotions: bool = True,
    planogram: Any = _read_planogram,
    sales_history: Any | None = _read_sales,
    get_shelf_state: Any | None = None,
    get_inventory: Any | None = None,
) -> ToolRegistry:
    registry = build_store_registry(store)
    if get_inventory is not None:
        bind_read_port(registry, "get_inventory", get_inventory)
    if sales_history is not None:
        bind_read_port(registry, "get_sales_history", sales_history)
    bind_read_port(registry, "forecast_demand", _read_forecast)
    if promotions:
        bind_read_port(registry, "get_promotions", _read_promotions)
    if planogram is not None:
        bind_read_port(registry, "get_planogram", planogram)
    if get_shelf_state is not None:
        registry.bind_catalog_tool("get_shelf_state", get_shelf_state)
    return registry


# ─── deterministic-path contract tests ──────────────────────────────────────


def test_investigator_executes_all_six_mandatory_reads_even_when_llm_unavailable() -> None:
    """All six mandatory read ports run, producing a sufficient bundle,
    even when the LLM provider's ``complete`` call raises. The LLM is
    an optional synthesis step that MUST NOT gate which reads are made
    or what the bundle records; a synthesis failure surfaces as
    :class:`InvestigatorError` so downstream stages can record
    ``provider_failed`` while the deterministic reads still ran.
    """
    store = _MemoryStore([_p017()])
    registry = _registry(store)

    # A provider failure during synthesis surfaces as
    # ``InvestigatorError``; the deterministic reads still ran before
    # the synthesis step (they're the first thing the investigator
    # does) so the store is unchanged.
    before = store.view()
    with pytest.raises(InvestigatorError):
        asyncio.run(
            investigate(
                _start(),
                provider=_RaisingProvider(),
                registry=registry,
                collected_at=COLLECTED_AT,
            )
        )
    after = store.view()
    assert before == after


def test_investigator_calls_per_sku_reads_with_event_sku() -> None:
    """The deterministic per-SKU reads
    (``get_inventory``, ``get_sales_history``, ``forecast_demand``,
    ``get_promotions``) are called with ``sku=event.sku``; the
    ``get_planogram`` call takes no args.
    """
    store = _MemoryStore([_p017()])
    seen: dict[str, Any] = {}

    def observed_sales(args: Any) -> dict[str, Any]:
        seen["get_sales_history"] = dict(args)
        return _read_sales(args)

    def observed_forecast(args: Any) -> dict[str, Any]:
        seen["forecast_demand"] = dict(args)
        return _read_forecast(args)

    def observed_promo(args: Any) -> dict[str, Any]:
        seen["get_promotions"] = dict(args)
        return _read_promotions(args)

    def observed_planogram(args: Any) -> dict[str, Any]:
        seen["get_planogram"] = dict(args)
        return _read_planogram(args)

    registry = ToolRegistry()
    registry.bind_catalog_tool("get_store_state", lambda _a: store.view().model_dump())

    def observed_inventory(args: Any) -> dict[str, Any]:
        seen["get_inventory"] = dict(args)
        product = store.inventory(args.sku)
        if product is None:
            raise ToolFailure(NOT_FOUND, f"SKU {args.sku} is not in the store.")
        return product.model_dump()

    def observed_shelf(args: Any) -> dict[str, Any]:
        seen["get_shelf_state"] = dict(args)
        products = [
            p.model_dump() for p in store.view().products if p.shelf_id == args.shelf_id
        ]
        if not products:
            raise ToolFailure(NOT_FOUND, f"Shelf {args.shelf_id} is not in the store.")
        return {"shelf_id": args.shelf_id, "products": products}

    registry.bind_catalog_tool("get_inventory", observed_inventory)
    registry.bind_catalog_tool("get_shelf_state", observed_shelf)
    bind_read_port(registry, "get_sales_history", observed_sales)
    bind_read_port(registry, "forecast_demand", observed_forecast)
    bind_read_port(registry, "get_promotions", observed_promo)
    bind_read_port(registry, "get_planogram", observed_planogram)

    bundle = asyncio.run(
        investigate(
            _start(),
            provider=_EmptyToolCallProvider(),
            registry=registry,
            collected_at=COLLECTED_AT,
        )
    )

    assert bundle.is_sufficient is True

    # Per-SKU reads use event.sku.
    assert seen["get_inventory"]["sku"] == TRIGGER.sku
    assert seen["get_sales_history"]["sku"] == TRIGGER.sku
    assert seen["forecast_demand"]["sku"] == TRIGGER.sku
    assert seen["get_promotions"]["sku"] == TRIGGER.sku

    # The deterministic window/horizon defaults are used.
    assert seen["get_sales_history"]["window_hours"] == 4
    assert seen["forecast_demand"]["horizon_hours"] == 4

    # ``get_shelf_state`` derives ``shelf_id`` from the inventory payload
    # (``A02`` is the P017 shelf), not from the LLM's tool_choice output.
    assert seen["get_shelf_state"]["shelf_id"] == "A02"

    # ``get_planogram`` takes no arguments.
    assert seen["get_planogram"] == {}


def test_bundle_sufficient_only_when_all_six_hits_succeed() -> None:
    """``bundle.is_sufficient`` is True iff every mandatory source has
    a successful versioned read. Removing any one of the six readers
    flips the bundle to insufficient.
    """
    store = _MemoryStore([_p017()])

    # First — the happy path: all six bound → bundle sufficient.
    full_registry = _registry(store)
    bundle = asyncio.run(
        investigate(
            _start(),
            provider=_EmptyToolCallProvider(),
            registry=full_registry,
            collected_at=COLLECTED_AT,
        )
    )
    assert bundle.is_sufficient is True
    for source, _tool in MANDATORY_SOURCES:
        item = next(item for item in bundle.items if item.event_type == source)
        assert "value" in item.payload, f"{source} missing a value"

    # Now drop each bound reader in turn (except ``get_inventory`` which
    # is bound by ``build_store_registry`` and cannot be skipped via the
    # helper). For each dropped port, the bundle must flip to
    # insufficient and the dropped source must appear in the missing
    # list.
    for drop_source, drop_tool in MANDATORY_SOURCES:
        if drop_source == "inventory":
            continue
        registry = ToolRegistry()
        registry.bind_catalog_tool(
            "get_store_state",
            lambda _a: store.view().model_dump(),
        )
        registry.bind_catalog_tool(
            "get_inventory",
            lambda a: store.inventory(a.sku).model_dump(),
        )
        if drop_source != "shelf":
            registry.bind_catalog_tool(
                "get_shelf_state",
                lambda a: {
                    "shelf_id": a.shelf_id,
                    "products": [
                        p.model_dump()
                        for p in store.view().products
                        if p.shelf_id == a.shelf_id
                    ],
                },
            )
        if drop_tool != "get_sales_history":
            bind_read_port(registry, "get_sales_history", _read_sales)
        if drop_tool != "forecast_demand":
            bind_read_port(registry, "forecast_demand", _read_forecast)
        if drop_tool != "get_promotions":
            bind_read_port(registry, "get_promotions", _read_promotions)
        if drop_tool != "get_planogram":
            bind_read_port(registry, "get_planogram", _read_planogram)
        bundle = asyncio.run(
            investigate(
                _start(),
                provider=_EmptyToolCallProvider(),
                registry=registry,
                collected_at=COLLECTED_AT,
            )
        )
        assert bundle.is_sufficient is False, (
            f"dropping {drop_source} must flip is_sufficient to False"
        )
        missing = [
            item.payload["source"]
            for item in bundle.items
            if item.event_type == "insufficient_evidence"
        ]
        assert drop_source in missing, (
            f"expected {drop_source} in missing list, got {missing}"
        )


def test_investigator_does_not_swallow_provider_errors_silently_in_synthesis() -> None:
    """Provider errors during the synthesis step are logged AND
    re-raised as :class:`InvestigatorError`. The deterministic read
    path is the source of truth; the LLM only adds annotations.
    """
    store = _MemoryStore([_p017()])
    registry = _registry(store)
    with pytest.raises(InvestigatorError) as caught:
        asyncio.run(
            investigate(
                _start(),
                provider=_RaisingProvider(),
                registry=registry,
                collected_at=COLLECTED_AT,
            )
        )
    assert caught.value.correlation_id == CORRELATION_ID
    assert "llm unavailable" not in str(caught.value)


def test_investigator_deterministic_tool_calls_have_one_per_mandatory_source() -> None:
    """The private ``_deterministic_tool_calls`` helper emits exactly
    one ``LlmToolCall`` per ``MANDATORY_SOURCES`` entry, with valid
    arguments derived from the event.
    """
    from retailtwin_api.agents.investigator.evidence import (
        _deterministic_tool_calls,
        _derive_shelf_id,
    )
    from retailtwin_api.llm.contracts import LlmToolCall
    from retailtwin_api.agents.orchestrator.tool_registry import ToolResult

    event = TRIGGER
    inventory_output = {"sku": event.sku, "shelf_id": "A02", "version": 1}
    inv_result = ToolResult(
        ok=True,
        name="get_inventory",
        capability=__import__(
            "retailtwin_api.contracts", fromlist=["ToolCapability"]
        ).ToolCapability.READ,
        output=inventory_output,
        correlation_id=event.correlation_id,
    )

    shelf_id = _derive_shelf_id(inv_result)
    calls = _deterministic_tool_calls(event, shelf_id=shelf_id)

    assert len(calls) == len(MANDATORY_SOURCES)
    names = [call.name for call in calls]
    expected_names = [tool for _source, tool in MANDATORY_SOURCES]
    assert names == expected_names

    # Every call is an LlmToolCall with the right shape.
    for call in calls:
        assert isinstance(call, LlmToolCall)
        assert call.id
        assert call.name
        assert isinstance(call.arguments, dict)

    # Per-SKU reads carry event.sku.
    sku_args = {tool: call.arguments.get("sku") for tool, call in zip(expected_names, calls)}
    assert sku_args["get_inventory"] == event.sku
    assert sku_args["get_sales_history"] == event.sku
    assert sku_args["forecast_demand"] == event.sku
    assert sku_args["get_promotions"] == event.sku

    # Store-level read (planogram) takes no arguments.
    planogram_call = next(call for call in calls if call.name == "get_planogram")
    assert planogram_call.arguments == {}

    # Per-shelf read carries the derived shelf_id.
    shelf_call = next(call for call in calls if call.name == "get_shelf_state")
    assert shelf_call.arguments == {"shelf_id": "A02"}


def test_investigator_derives_shelf_id_from_inventory_payload() -> None:
    """``_derive_shelf_id`` returns the inventory's ``shelf_id`` when
    the read succeeded and the payload carries a non-empty value;
    otherwise it returns a non-matching placeholder so the shelf read
    fails with NOT_FOUND rather than fabricating a shelf.
    """
    from retailtwin_api.agents.investigator.evidence import (
        _derive_shelf_id,
        _SHELF_PLACEHOLDER,
    )
    from retailtwin_api.agents.orchestrator.tool_registry import ToolResult
    from retailtwin_api.contracts import ToolCapability

    ok = ToolResult(
        ok=True, name="get_inventory", capability=ToolCapability.READ,
        output={"sku": "P017", "shelf_id": "A02", "version": 1},
    )
    assert _derive_shelf_id(ok) == "A02"

    ok_blank = ToolResult(
        ok=True, name="get_inventory", capability=ToolCapability.READ,
        output={"sku": "P017", "shelf_id": "", "version": 1},
    )
    assert _derive_shelf_id(ok_blank) == _SHELF_PLACEHOLDER

    failed = ToolResult(
        ok=False, name="get_inventory", capability=ToolCapability.READ,
        error_code=SOURCE_UNAVAILABLE,
    )
    assert _derive_shelf_id(failed) == _SHELF_PLACEHOLDER