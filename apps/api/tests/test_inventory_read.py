"""CI proof for one get_inventory read. No network and no model call."""

from __future__ import annotations

import asyncio
import json

import pytest

from retailtwin_api.agents.orchestrator.inventory_read import (
    InventoryReadError,
    read_inventory,
)
from retailtwin_api.firestore_twin import (
    InMemoryTwinRepository,
    InventoryDocument,
    InventorySeed,
)
from retailtwin_api.llm.contracts import LlmToolCall, ProviderError
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.schemas import ProductInventory

STORE = "store-001"
SKU = "P001"
CORRELATION = "read-p001"


class _GuardedTwin(InMemoryTwinRepository):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.sealed = False

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        self.reads += 1
        return super().get_inventory(store_id, sku)

    def get_store(self, store_id: str):  # type: ignore[override]
        raise AssertionError("get_store")

    def list_inventory(self, store_id: str):  # type: ignore[override]
        raise AssertionError("list_inventory")

    def upsert_inventory(self, item: InventoryDocument, expected_version: int | None) -> InventoryDocument:
        if self.sealed:
            raise AssertionError("upsert_inventory")
        return super().upsert_inventory(item, expected_version)

    def seed(self, store_id: str, version: str, items: list[InventorySeed] | tuple[InventorySeed, ...]) -> None:
        if self.sealed:
            raise AssertionError("seed")
        super().seed(store_id, version, items)

    def reset(self, store_id: str) -> None:
        raise AssertionError("reset")

    def commit_inventory(self, store_id: str, items):  # type: ignore[no-untyped-def]
        raise AssertionError("commit_inventory")


class _ExplodingProvider(FakeLlmProvider):
    async def complete(self, request):  # type: ignore[no-untyped-def]
        self._call_count += 1
        raise ProviderError("bearer ya29.not-a-token")


def _twin() -> _GuardedTwin:
    twin = _GuardedTwin()
    twin.seed(
        STORE,
        "v1",
        [
            InventorySeed(
                sku=SKU,
                shelf_id="A01",
                slot_id="A01-S01",
                facings=3,
                shelf_quantity=8,
                backroom_quantity=42,
            )
        ],
    )
    twin.sealed = True
    twin.reads = 0
    return twin


def _call(sku: str = SKU) -> LlmToolCall:
    return LlmToolCall(id="call-1", name="get_inventory", arguments={"sku": sku})


def _provider(*responses: FakeLlmProvider.Response) -> FakeLlmProvider:
    return FakeLlmProvider(responses=list(responses))


def _read(twin: InMemoryTwinRepository, provider: FakeLlmProvider, sku: str = SKU):
    return asyncio.run(
        read_inventory(
            twin,
            provider=provider,
            store_id=STORE,
            sku=sku,
            correlation_id=CORRELATION,
            model="fake-test",
        )
    )


def test_successful_read_matches_the_twin_document() -> None:
    twin = _twin()
    document = twin.get_inventory(STORE, SKU)
    assert document is not None
    twin.reads = 0
    before = document.model_dump()
    provider = _provider(
        FakeLlmProvider.Response(
            content="shelf_quantity is 999",
            tool_calls=[_call()],
        )
    )

    result = _read(twin, provider)

    assert result.ok is True
    assert result.name == "get_inventory"
    assert result.error_code is None
    assert result.correlation_id == CORRELATION
    assert result.output == document.to_product_inventory()
    assert result.output == ProductInventory.model_validate(result.output).model_dump()
    assert "updated_at" not in (result.output or {})
    assert "999" not in json.dumps(result.model_dump())
    assert twin.get_inventory(STORE, SKU) is not None
    assert twin.get_inventory(STORE, SKU).model_dump() == before  # type: ignore[union-attr]
    sent = provider.call_history[0]
    assert [tool.name for tool in sent.tools] == ["get_inventory"]
    assert sent.tool_choice is not None
    assert sent.tool_choice.mode == "required_tool"
    assert sent.tool_choice.name == "get_inventory"
    assert sent.max_tokens is None
    assert sent.metadata["vertex_thinking_budget"] == "0"
    assert "move_product" not in {tool.name for tool in sent.tools}
    assert "submit_action_for_commit" not in {tool.name for tool in sent.tools}


def test_missing_sku_is_a_controlled_not_found() -> None:
    twin = _twin()
    provider = _provider(FakeLlmProvider.Response(tool_calls=[_call("NO-SUCH-SKU")]))

    result = _read(twin, provider, sku="NO-SUCH-SKU")

    assert result.ok is False
    assert result.error_code == "not_found"
    assert result.output is None
    assert result.message == "SKU NO-SUCH-SKU is not in the store."
    assert twin.get_inventory(STORE, "NO-SUCH-SKU") is None
    assert twin.get_inventory(STORE, SKU) is not None


def test_prose_without_a_tool_call_fails_closed() -> None:
    twin = _twin()
    provider = _provider(FakeLlmProvider.Response(content='{"shelf_quantity": 999}'))

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, provider)

    assert caught.value.reason == "no_tool_call"
    assert "999" not in str(caught.value)
    assert twin.reads == 0


def test_wrong_tool_is_not_executed() -> None:
    twin = _twin()
    provider = _provider(
        FakeLlmProvider.Response(
            tool_calls=[LlmToolCall(id="call-1", name="move_product", arguments={"sku": SKU})]
        )
    )

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, provider)

    assert caught.value.reason == "unexpected_tool"
    assert twin.reads == 0


def test_extra_tool_call_is_not_executed() -> None:
    twin = _twin()
    provider = _provider(
        FakeLlmProvider.Response(tool_calls=[_call(), _call()])
    )

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, provider)

    assert caught.value.reason == "unexpected_tool"
    assert twin.reads == 0


def test_different_sku_is_not_executed() -> None:
    twin = _twin()
    provider = _provider(FakeLlmProvider.Response(tool_calls=[_call("P002")]))

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, provider)

    assert caught.value.reason == "unexpected_sku"
    assert twin.reads == 0


def test_extra_arguments_are_not_executed() -> None:
    twin = _twin()
    provider = _provider(
        FakeLlmProvider.Response(
            tool_calls=[
                LlmToolCall(
                    id="call-1",
                    name="get_inventory",
                    arguments={"sku": SKU, "shelf_quantity": 1},
                )
            ]
        )
    )

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, provider)

    assert caught.value.reason == "invalid_arguments"
    assert twin.reads == 0


def test_provider_failure_does_not_echo_the_provider_message() -> None:
    twin = _twin()

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, _ExplodingProvider())

    assert caught.value.reason == "provider_failed"
    assert "ya29" not in str(caught.value)
    assert "bearer" not in str(caught.value).casefold()
    assert twin.reads == 0


def test_handler_failure_is_not_replaced_by_model_prose() -> None:
    twin = _twin()

    def explode(self: _GuardedTwin, store_id: str, sku: str) -> InventoryDocument | None:
        self.reads += 1
        raise RuntimeError("store unavailable")

    twin.get_inventory = explode.__get__(twin, _GuardedTwin)  # type: ignore[method-assign]
    provider = _provider(
        FakeLlmProvider.Response(content="shelf_quantity is 999", tool_calls=[_call()])
    )

    result = _read(twin, provider)

    assert result.ok is False
    assert result.error_code == "handler_failed"
    assert result.message == "The tool failed."
    assert result.output is None
    assert "999" not in json.dumps(result.model_dump())
    assert "unavailable" not in (result.message or "")


def test_mismatched_document_fails_closed() -> None:
    twin = _twin()
    original = twin.get_inventory

    def swap(self: _GuardedTwin, store_id: str, sku: str) -> InventoryDocument | None:
        self.reads += 1
        document = original(store_id, sku)
        if document is None:
            return None
        return document.model_copy(update={"sku": "P999"})

    twin.get_inventory = swap.__get__(twin, _GuardedTwin)  # type: ignore[method-assign]
    provider = _provider(FakeLlmProvider.Response(tool_calls=[_call()]))

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, provider)

    assert caught.value.reason == "mismatched_document"


def test_document_from_another_store_fails_closed() -> None:
    twin = _twin()

    def swap(self: _GuardedTwin, store_id: str, sku: str) -> InventoryDocument | None:
        self.reads += 1
        document = InMemoryTwinRepository.get_inventory(self, store_id, sku)
        if document is None:
            return None
        return document.model_copy(update={"store_id": "store-999"})

    twin.get_inventory = swap.__get__(twin, _GuardedTwin)  # type: ignore[method-assign]
    provider = _provider(FakeLlmProvider.Response(tool_calls=[_call()]))

    with pytest.raises(InventoryReadError) as caught:
        _read(twin, provider)

    assert caught.value.reason == "mismatched_document"
    stored = InMemoryTwinRepository.get_inventory(twin, STORE, SKU)
    assert stored is not None
    assert stored.store_id == STORE


def test_untyped_tool_output_fails_closed() -> None:
    from retailtwin_api.agents.orchestrator.inventory_read import _proven
    from retailtwin_api.agents.orchestrator.tool_registry import ToolResult
    from retailtwin_api.contracts import ToolCapability

    result = ToolResult(
        ok=True,
        name="get_inventory",
        capability=ToolCapability.READ,
        output={"sku": SKU},
        correlation_id=CORRELATION,
    )

    with pytest.raises(InventoryReadError) as caught:
        _proven(result, store_id=STORE, sku=SKU, correlation_id=CORRELATION)

    assert caught.value.reason == "untyped_result"
    assert SKU not in str(caught.value)


def test_blank_input_does_not_call_the_provider() -> None:
    twin = _twin()
    provider = _provider()

    with pytest.raises(InventoryReadError) as caught:
        asyncio.run(
            read_inventory(
                twin,
                provider=provider,
                store_id=STORE,
                sku="",
                correlation_id=CORRELATION,
                model="fake-test",
            )
        )

    assert caught.value.reason == "invalid_request"
    assert provider.call_count == 0
    assert twin.reads == 0
