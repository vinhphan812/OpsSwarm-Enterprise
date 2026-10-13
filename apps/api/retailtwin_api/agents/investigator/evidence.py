"""Collect versioned evidence for one investigation.

The provider chooses which read tools to call. Their results are the only
evidence. Model prose is ignored. A mandatory source without a versioned
result is recorded as insufficient_evidence and is not guessed.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.tool_registry import (
    SOURCE_UNAVAILABLE,
    ToolFailure,
    ToolRegistry,
    ToolResult,
)
from retailtwin_api.contracts import EvidenceBundle, EvidenceItem, ToolCapability
from retailtwin_api.llm.contracts import (
    LlmMessage,
    LlmProvider,
    LlmRequest,
    LlmToolCall,
    ToolChoicePolicy,
)
from retailtwin_api.schemas import StoreEvent

log = logging.getLogger(__name__)

_MODEL = "investigator"
_INSTRUCTION = (
    "Call the read tools that describe this sale. "
    "Use only tool results. Do not invent quantities, forecasts, promotions, or planogram facts. "
    "If a tool is unavailable, leave that source missing."
)

# Source name, then the catalog tool that can observe it.
MANDATORY_SOURCES: tuple[tuple[str, str], ...] = (
    ("inventory", "get_inventory"),
    ("shelf", "get_shelf_state"),
    ("sales_history", "get_sales_history"),
    ("forecast", "forecast_demand"),
    ("promotions", "get_promotions"),
    ("planogram", "get_planogram"),
)
_SOURCE_OF_TOOL = {tool: source for source, tool in MANDATORY_SOURCES}

NOT_REQUESTED = "not_requested"
MISSING_VERSION = "missing_version"
ENTITY_MISMATCH = "entity_mismatch"


class InvestigatorError(Exception):
    """Evidence collection failed. The message does not include the provider error."""

    def __init__(self, correlation_id: str) -> None:
        self.correlation_id = correlation_id
        super().__init__(f"Evidence collection failed for {correlation_id}.")


class ReadPort(Protocol):
    """Deterministic reader injected for one catalog tool."""

    def __call__(self, args: Any) -> Mapping[str, Any] | None: ...


@dataclass
class _Hit:
    success: dict[str, Any] | None = None
    failure_reason: str | None = None
    entity_id: str | None = None


def bind_read_port(registry: ToolRegistry, tool_name: str, reader: ReadPort) -> None:
    """Bind a catalog read tool to ``reader``.

    ``None``, a result without a version, or any exception becomes
    ``source_unavailable``. The tool message does not include the original
    exception text.
    """

    def handler(args: Any) -> Mapping[str, Any]:
        try:
            output = reader(args)
            if output is None or not isinstance(output, Mapping) or "version" not in output:
                raise ToolFailure(SOURCE_UNAVAILABLE, "The source failed.")
            copied = dict(output)
        except ToolFailure:
            raise
        except Exception:
            log.error("read port failed tool=%s", tool_name)
            raise ToolFailure(SOURCE_UNAVAILABLE, "The source failed.") from None
        return copied

    registry.bind_catalog_tool(tool_name, handler)


async def investigate(
    start: InvestigationStart,
    *,
    provider: LlmProvider,
    registry: ToolRegistry,
    collected_at: datetime,
) -> EvidenceBundle:
    """Return versioned evidence for ``start``.

    Only registry read tools that the provider requests are executed. A
    mandatory source that does not return a version is insufficient. This
    function does not write the store.
    """

    event = start.event
    request = LlmRequest(
        model=_MODEL,
        messages=[
            LlmMessage(role="system", content=_INSTRUCTION),
            LlmMessage(role="user", content=_handoff(event)),
        ],
        tools=registry.llm_tools(capabilities={ToolCapability.READ}),
        tool_choice=ToolChoicePolicy(mode="tool_choice"),
        metadata={
            "correlation_id": event.correlation_id,
            "investigation_id": start.investigation_id,
            "sku": event.sku,
        },
    )
    try:
        response = await provider.complete(request)
    except Exception:
        log.exception(
            "evidence collection failed correlation_id=%s",
            event.correlation_id,
        )
        raise InvestigatorError(event.correlation_id) from None

    # Tool results are the only evidence. response.content is not read.
    results = registry.execute_tool_calls(
        response.tool_calls,
        granted={ToolCapability.READ},
        correlation_id=event.correlation_id,
    )
    states = {source: _Hit() for source, _name in MANDATORY_SOURCES}
    for call, result in zip(response.tool_calls, results, strict=True):
        _record(states, call, result, event, collected_at)
    return _bundle(event, states, collected_at)


def _handoff(event: StoreEvent) -> str:
    return json.dumps(
        {
            "correlation_id": event.correlation_id,
            "event_id": event.event_id,
            "sku": event.sku,
            "store_id": event.store_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _record(
    states: dict[str, _Hit],
    call: LlmToolCall,
    result: ToolResult,
    event: StoreEvent,
    collected_at: datetime,
) -> None:
    source = _SOURCE_OF_TOOL.get(result.name)
    if source is None:
        return
    hit = states[source]
    entity_id = _entity_id(source, call, result.output, event)
    if _wrong_sku_argument(call, event.sku):
        _reject(hit, ENTITY_MISMATCH, entity_id)
        return
    output = result.output
    if not result.ok or not isinstance(output, dict):
        _reject(hit, result.error_code or SOURCE_UNAVAILABLE, entity_id)
        return
    if not _same_entity(source, output, event.sku):
        _reject(hit, ENTITY_MISMATCH, entity_id)
        return
    version = _read_version(source, output, event.sku)
    if version is None:
        _reject(hit, MISSING_VERSION, entity_id)
        return
    hit.success = {
        "source": source,
        "entity_id": entity_id,
        "version": version,
        "observed_at": _observed_at(output, collected_at),
        "value": copy.deepcopy(output),
    }
    hit.failure_reason = None
    hit.entity_id = entity_id


def _reject(hit: _Hit, reason: str, entity_id: str) -> None:
    if hit.success is not None:
        return
    hit.failure_reason = reason
    hit.entity_id = entity_id


def _bundle(
    event: StoreEvent,
    states: dict[str, _Hit],
    collected_at: datetime,
) -> EvidenceBundle:
    items: list[EvidenceItem] = []
    versions: dict[str, str] = {}
    missing: list[str] = []
    for source, _name in MANDATORY_SOURCES:
        hit = states[source]
        if hit.success is None:
            missing.append(source)
            items.append(
                EvidenceItem(
                    event_type="insufficient_evidence",
                    payload={
                        "source": source,
                        "entity_id": hit.entity_id or _default_entity(source, event),
                        "reason": hit.failure_reason or NOT_REQUESTED,
                    },
                )
            )
            continue
        items.append(EvidenceItem(event_type=source, payload=hit.success))
        if source == "inventory":
            versions[event.sku] = str(hit.success["version"])
    sufficient = not missing
    log.info(
        "evidence collected correlation_id=%s sku=%s is_sufficient=%s missing=%s",
        event.correlation_id,
        event.sku,
        sufficient,
        ",".join(missing),
    )
    return EvidenceBundle(
        bundle_id=f"bundle-{event.correlation_id}-{event.sku}",
        provenance="tool-registry",
        source="investigator",
        entity_versions=versions,
        collected_at=collected_at,
        freshness=collected_at,
        store_id=event.store_id,
        correlation_id=event.correlation_id,
        is_sufficient=sufficient,
        items=items,
    )


def _wrong_sku_argument(call: LlmToolCall, sku: str) -> bool:
    argument = call.arguments.get("sku")
    return isinstance(argument, str) and argument != sku


def _same_entity(source: str, output: Mapping[str, Any], sku: str) -> bool:
    output_sku = output.get("sku")
    if isinstance(output_sku, str) and output_sku != sku:
        return False
    if source != "shelf":
        return True
    products = output.get("products")
    if not isinstance(products, list):
        return False
    return any(isinstance(product, Mapping) and product.get("sku") == sku for product in products)


def _read_version(source: str, output: Mapping[str, Any], sku: str) -> str | None:
    found = _version_text(output.get("version"))
    if found is not None:
        return found
    if source != "shelf":
        return None
    products = output.get("products")
    if not isinstance(products, list):
        return None
    for product in products:
        if not isinstance(product, Mapping) or product.get("sku") != sku:
            continue
        return _version_text(product.get("version"))
    return None


def _version_text(raw: object) -> str | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        return text or None
    if isinstance(raw, int):
        return str(raw)
    return None


def _observed_at(output: Mapping[str, Any], collected_at: datetime) -> str:
    raw = output.get("observed_at")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return collected_at.isoformat()


def _entity_id(
    source: str,
    call: LlmToolCall,
    output: object,
    event: StoreEvent,
) -> str:
    if source == "planogram":
        return event.store_id
    if source == "shelf":
        candidates: list[object] = []
        if isinstance(output, Mapping):
            candidates.append(output.get("shelf_id"))
        candidates.append(call.arguments.get("shelf_id"))
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return event.sku


def _default_entity(source: str, event: StoreEvent) -> str:
    if source == "planogram":
        return event.store_id
    return event.sku
