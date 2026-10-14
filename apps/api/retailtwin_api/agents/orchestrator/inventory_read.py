"""One required ``get_inventory`` read against the Live Twin.

The typed tool result is the inventory. Model prose is not. The request
offers no simulation or commit tool, and this module does not write the twin.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, NoReturn, Protocol

from pydantic import ValidationError

from retailtwin_api.agents.orchestrator.tool_registry import (
    NOT_FOUND,
    ToolFailure,
    ToolRegistry,
    ToolResult,
)
from retailtwin_api.contracts import ToolCapability
from retailtwin_api.firestore_twin import InventoryDocument
from retailtwin_api.llm.contracts import (
    LlmMessage,
    LlmProvider,
    LlmRequest,
    ToolChoicePolicy,
)
from retailtwin_api.schemas import ProductInventory

log = logging.getLogger(__name__)

TOOL_NAME = "get_inventory"
# A Firestore GET uses a 30s socket timeout. The registry must wait longer than that.
_TOOL_TIMEOUT_S = 60.0
# gemini-2.5-flash spends output tokens on thought text. This read asks for none
# so the forced function call is the output. Callers that omit the key are unchanged.
_THINKING_BUDGET_KEY = "vertex_thinking_budget"

_INSTRUCTION = (
    "Call get_inventory exactly once. "
    "Pass the sku from the user message unchanged. "
    "Do not state quantities, shelf ids, or versions yourself."
)


class InventoryReader(Protocol):
    """Read one inventory document. This protocol has no write method."""

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None: ...


class InventoryReadError(Exception):
    """The read did not return the requested SKU's tool result.

    ``reason`` is a stable code. The message does not include provider text.
    """

    def __init__(self, correlation_id: str, reason: str) -> None:
        self.correlation_id = correlation_id
        self.reason = reason
        super().__init__(f"Inventory read failed for {correlation_id}.")


class _InventoryStore:
    def __init__(self, twin: InventoryReader, store_id: str) -> None:
        self._twin = twin
        self._store_id = store_id

    def inventory(self, sku: str) -> ProductInventory | None:
        document = self._twin.get_inventory(self._store_id, sku)
        if document is None:
            return None
        return ProductInventory.model_validate(document.to_product_inventory())


def _log(correlation_id: str, sku: str, ok: bool, error_code: str | None) -> None:
    log.info(
        "inventory read correlation_id=%s sku=%s tool=%s ok=%s error_code=%s",
        correlation_id,
        sku,
        TOOL_NAME,
        ok,
        error_code,
    )


def _fail(correlation_id: str, sku: str, reason: str) -> NoReturn:
    _log(correlation_id, sku, False, reason)
    raise InventoryReadError(correlation_id, reason)


def _registry(store: _InventoryStore) -> ToolRegistry:
    registry = ToolRegistry()

    def get_inventory(args: Any) -> Mapping[str, Any]:
        item = store.inventory(args.sku)
        if item is None:
            raise ToolFailure(NOT_FOUND, f"SKU {args.sku} is not in the store.")
        return item.model_dump()

    registry.bind_catalog_tool(TOOL_NAME, get_inventory, timeout_s=_TOOL_TIMEOUT_S)
    return registry


def _proven(result: ToolResult, *, store_id: str, sku: str, correlation_id: str) -> ToolResult:
    if not result.ok:
        return result
    try:
        parsed = ProductInventory.model_validate(result.output)
    except ValidationError:
        _fail(correlation_id, sku, "untyped_result")
    if parsed.sku != sku or parsed.store_id != store_id:
        _fail(correlation_id, sku, "mismatched_document")
    return result.model_copy(update={"output": parsed.model_dump()})


async def read_inventory(
    twin: InventoryReader,
    *,
    provider: LlmProvider,
    store_id: str,
    sku: str,
    correlation_id: str,
    model: str,
) -> ToolResult:
    """Ask ``provider`` for one ``get_inventory`` call and execute only that call.

    A missing SKU is ``ToolResult(ok=False, error_code="not_found")``. No tool
    call, a different tool, or a different SKU raises ``InventoryReadError``
    and does not execute the call. ``response.content`` is ignored.
    """

    if store_id == "" or sku == "" or correlation_id == "" or model == "":
        _fail(correlation_id or "missing", sku, "invalid_request")

    registry = _registry(_InventoryStore(twin, store_id))
    request = LlmRequest(
        model=model,
        messages=[
            LlmMessage(role="system", content=_INSTRUCTION),
            LlmMessage(
                role="user",
                content=json.dumps(
                    {"store_id": store_id, "sku": sku},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        ],
        temperature=0,
        tools=registry.llm_tools(),
        tool_choice=ToolChoicePolicy(mode="required_tool", name=TOOL_NAME),
        metadata={
            "correlation_id": correlation_id,
            "store_id": store_id,
            "sku": sku,
            _THINKING_BUDGET_KEY: "0",
        },
    )
    try:
        response = await provider.complete(request)
    except Exception as exc:
        log.error(
            "inventory read failed correlation_id=%s sku=%s error_type=%s",
            correlation_id,
            sku,
            type(exc).__name__,
        )
        _fail(correlation_id, sku, "provider_failed")

    calls = response.tool_calls
    if len(calls) == 0:
        _fail(correlation_id, sku, "no_tool_call")
    if len(calls) != 1 or calls[0].name != TOOL_NAME:
        _fail(correlation_id, sku, "unexpected_tool")
    arguments = calls[0].arguments
    if arguments.get("sku") != sku:
        _fail(correlation_id, sku, "unexpected_sku")
    if arguments != {"sku": sku}:
        _fail(correlation_id, sku, "invalid_arguments")

    result = registry.execute_tool_calls(
        calls,
        granted={ToolCapability.READ},
        correlation_id=correlation_id,
    )[0]
    proven = _proven(result, store_id=store_id, sku=sku, correlation_id=correlation_id)
    _log(correlation_id, sku, proven.ok, proven.error_code)
    return proven
