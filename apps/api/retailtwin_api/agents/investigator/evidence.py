"""Collect versioned evidence for one investigation.

All six mandatory read ports (``MANDATORY_SOURCES``) are executed
deterministically — driven by the source list, NOT by the LLM's
tool-choice output. The LLM is preserved as an OPTIONAL synthesis
step that may summarize or annotate observations; its tool-choice
output is never consulted for the read set, and its absence (or
failure) does not invalidate the bundle. Their results are the only
evidence. Model prose is ignored. A mandatory source without a
versioned result is recorded as ``insufficient_evidence`` and is not
guessed.

Each mandatory source's ``bind_read_port`` reader returns a Mapping with a
``version`` key. For the BigQuery-backed ``get_sales_history`` reader the
``version`` is a deterministic digest of ``query_window``,
``source_watermark``, ``data_lineage``, and ``content_digest`` (a sha256
over the returned rows), so two distinct BigQuery jobs that return the
same rows reproduce the same ``version``. The BigQuery ``query_job_id``
is kept on the payload for debugging. The ``ProductInventory.version``
key for ``get_inventory`` is the inventory canonical version. The
EvidenceBundle's ``entity_versions`` map carries the canonical
``inventory`` version keyed by SKU; ``sales_history`` and ``forecast``
attach their ``version`` to the matching item payload so downstream
consumers — Planner, Simulator, KPI evaluator — can thread the
demand-evidence version end-to-end.

When a mandatory source's reader returns ``None`` (e.g. the BigQuery
``retailtwin.sales_events`` query returns no rows in the canonical window)
or raises, the wrapping ``bind_read_port`` handler converts the failure
to ``source_unavailable`` and the investigator records it as
``insufficient_evidence`` with the typed reason
``sales_history_unavailable`` for the BigQuery-backed sales_history port.
The investigator never invents a number.
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
# Reason code for when the BigQuery-backed ``get_sales_history`` reader returns
# ``None`` (empty result) or raises. The reader converts both cases to ``None``,
# and the wrapping ``bind_read_port`` handler converts ``None`` to
# ``source_unavailable``; this code keeps the investigator's typed vocabulary
# aligned with issue #215 / ADR 0024.
SALES_HISTORY_UNAVAILABLE = "sales_history_unavailable"
# Sources whose ``version`` is surfaced on the bundle.
# ``inventory`` keys ``entity_versions`` by SKU; the BigQuery-backed
# ``sales_history`` and the deterministic ``forecast`` key
# ``source_versions`` by source name. The demand-evidence source
# (``sales_history``) is what the KPI evaluator reads to populate
# ``evaluator_version`` on a scored candidate.
DEMAND_EVIDENCE_SOURCE = "sales_history"


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

    All six mandatory read ports (``MANDATORY_SOURCES``) are executed
    deterministically — driven by the source list, NOT by the LLM's
    tool-choice output. The LLM is preserved as an OPTIONAL synthesis
    step that may summarize or annotate observations; its tool-choice
    output is never consulted for the read set, and its absence (or
    failure) does not invalidate the bundle.

    The deterministic ``get_shelf_state`` call uses ``shelf_id`` derived
    from the inventory payload (when the inventory read returns one).
    When inventory fails or omits ``shelf_id``, a non-matching
    placeholder is used and ``get_shelf_state`` is allowed to fail at
    the handler with ``NOT_FOUND``; the shelf source is then recorded
    as ``insufficient_evidence``. The investigator never invents a
    shelf.

    A mandatory source that does not return a versioned payload is
    insufficient. This function does not write the store.
    """

    event = start.event

    # Phase 1 — read get_inventory first so we can derive the SKU's
    # ``shelf_id`` for the deterministic ``get_shelf_state`` call.
    inv_call = LlmToolCall(
        id="det-inv",
        name="get_inventory",
        arguments={"sku": event.sku},
    )
    inv_results = registry.execute_tool_calls(
        [inv_call],
        granted={ToolCapability.READ},
        correlation_id=event.correlation_id,
    )
    inv_result = inv_results[0]
    shelf_id = _derive_shelf_id(inv_result)

    # Phase 2 — build and execute the remaining 5 deterministic reads.
    # ``get_inventory`` is reused (not re-executed) so the recorded
    # inventory result is identical to the one we used to derive
    # ``shelf_id``.
    remaining_calls: list[LlmToolCall] = [
        LlmToolCall(
            id="det-shelf",
            name="get_shelf_state",
            arguments={"shelf_id": shelf_id},
        ),
        LlmToolCall(
            id="det-sales",
            name="get_sales_history",
            arguments={"sku": event.sku, "window_hours": 4},
        ),
        LlmToolCall(
            id="det-forecast",
            name="forecast_demand",
            arguments={"sku": event.sku, "horizon_hours": 4},
        ),
        LlmToolCall(
            id="det-promo",
            name="get_promotions",
            arguments={"sku": event.sku},
        ),
        LlmToolCall(
            id="det-plan",
            name="get_planogram",
            arguments={},
        ),
    ]
    remaining_results = registry.execute_tool_calls(
        remaining_calls,
        granted={ToolCapability.READ},
        correlation_id=event.correlation_id,
    )

    calls = [inv_call, *remaining_calls]
    results = [inv_result, *remaining_results]
    states = {source: _Hit() for source, _name in MANDATORY_SOURCES}
    for call, result in zip(calls, results, strict=True):
        _record(states, call, result, event, collected_at)

    # Optional LLM synthesis — strictly advisory. The deterministic
    # reads above have already produced the bundle; the LLM may be
    # used to summarize or annotate, but its tool-choice output is
    # ignored and its failure does not invalidate the bundle.
    await _synthesize(start, provider, event, registry)

    return _bundle(event, states, collected_at)


def _deterministic_tool_calls(
    event: StoreEvent,
    *,
    shelf_id: str,
) -> list[LlmToolCall]:
    """Return one ``LlmToolCall`` per ``MANDATORY_SOURCES`` entry.

    The argument set is derived from the registered tool catalog and
    from the ``StoreEvent`` so that every call is valid for the tool's
    pydantic args model. For SKU-keyed reads (``get_inventory``,
    ``get_sales_history``, ``forecast_demand``, ``get_promotions``) the
    SKU is ``event.sku``. The store-level ``get_planogram`` takes no
    arguments. The per-shelf ``get_shelf_state`` requires a
    ``shelf_id``; the caller is expected to have derived it from the
    deterministic ``get_inventory`` payload via
    :func:`_derive_shelf_id`.
    """
    return [
        LlmToolCall(
            id="det-inv",
            name="get_inventory",
            arguments={"sku": event.sku},
        ),
        LlmToolCall(
            id="det-shelf",
            name="get_shelf_state",
            arguments={"shelf_id": shelf_id},
        ),
        LlmToolCall(
            id="det-sales",
            name="get_sales_history",
            arguments={"sku": event.sku, "window_hours": 4},
        ),
        LlmToolCall(
            id="det-forecast",
            name="forecast_demand",
            arguments={"sku": event.sku, "horizon_hours": 4},
        ),
        LlmToolCall(
            id="det-promo",
            name="get_promotions",
            arguments={"sku": event.sku},
        ),
        LlmToolCall(
            id="det-plan",
            name="get_planogram",
            arguments={},
        ),
    ]


def _derive_shelf_id(inv_result: ToolResult) -> str:
    """Return the ``shelf_id`` to use for the deterministic shelf read.

    When ``get_inventory`` succeeded and the payload carries a
    non-empty ``shelf_id``, return it. Otherwise return a non-matching
    placeholder so ``get_shelf_state`` fails with ``NOT_FOUND`` and
    ``_record`` marks the shelf source as ``insufficient_evidence``.
    The investigator never fabricates a shelf.
    """
    if inv_result.ok and isinstance(inv_result.output, dict):
        raw = inv_result.output.get("shelf_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return _SHELF_PLACEHOLDER


_SHELF_PLACEHOLDER = "det-shelf-placeholder"


async def _synthesize(
    start: InvestigationStart,
    provider: LlmProvider,
    event: StoreEvent,
    registry: ToolRegistry,
) -> None:
    """Run the optional LLM synthesis call.

    The deterministic reads above have already produced the bundle;
    the LLM may be used to summarize or annotate observations.
    ``tool_choice`` is set to ``"none"`` so the model is informed it
    must not pick tools — the read set is fixed by ``MANDATORY_SOURCES``
    and the model's tool-choice output is never consulted.

    A provider failure during synthesis is logged and re-raised as
    :class:`InvestigatorError` so downstream stages (the planner, the
    autonomy / replan loops) can still record ``provider_failed``. The
    deterministic bundle itself is already produced and the chain does
    not regress to "insufficient evidence" on a synthesis-only
    failure — only the chain's progress is gated on the LLM being
    reachable.
    """
    try:
        request = LlmRequest(
            model=_MODEL,
            messages=[
                LlmMessage(role="system", content=_INSTRUCTION),
                LlmMessage(role="user", content=_handoff(event)),
            ],
            tools=registry.llm_tools(capabilities={ToolCapability.READ}),
            tool_choice=ToolChoicePolicy(mode="none"),
            metadata={
                "correlation_id": event.correlation_id,
                "investigation_id": start.investigation_id,
                "sku": event.sku,
            },
        )
        await provider.complete(request)
    except Exception:
        log.warning(
            "investigator.llm_synthesis_unavailable correlation_id=%s; "
            "deterministic reads already produced the bundle.",
            event.correlation_id,
        )
        raise InvestigatorError(event.correlation_id) from None


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
    source_versions: dict[str, str] = {}
    missing: list[str] = []
    for source, _name in MANDATORY_SOURCES:
        hit = states[source]
        if hit.success is None:
            missing.append(source)
            reason = hit.failure_reason or NOT_REQUESTED
            if reason == SOURCE_UNAVAILABLE and source == "sales_history":
                # Typed vocabulary for the BigQuery-backed sales_history port
                # (issue #215 / ADR 0024): when the reader returns ``None`` or
                # raises, ``bind_read_port`` raises ``SOURCE_UNAVAILABLE``;
                # the bundle surfaces it as ``sales_history_unavailable`` so
                # downstream code can branch on the typed code.
                reason = SALES_HISTORY_UNAVAILABLE
            items.append(
                EvidenceItem(
                    event_type="insufficient_evidence",
                    payload={
                        "source": source,
                        "entity_id": hit.entity_id or _default_entity(source, event),
                        "reason": reason,
                    },
                )
            )
            continue
        items.append(EvidenceItem(event_type=source, payload=hit.success))
        if source == "inventory":
            # ``inventory`` is the only source keyed by SKU; the rest of the
            # chain (Planner, DCG, Executor) reads ``entity_versions[sku]``
            # to verify the proposal context against the live snapshot.
            versions[event.sku] = str(hit.success["version"])
        elif source in {"sales_history", "forecast"}:
            # ``sales_history`` is the BigQuery-backed demand evidence
            # (issue #215 / ADR 0024); its ``version`` is a deterministic
            # sha256[16] digest of ``query_window``, ``source_watermark``,
            # ``data_lineage``, and the row-level ``content_digest`` —
            # so two distinct BigQuery jobs returning the same rows
            # produce the same ``version``. The ``query_job_id`` is
            # kept alongside for debugging. ``forecast`` is the
            # deterministic demand forecast (issue #30) keyed by the
            # formula id. Both are surfaced under ``source_versions`` so
            # downstream code — KPI evaluator, audit trail — can read
            # the demand-evidence version without parsing the ``items``
            # list.
            source_versions[source] = str(hit.success["version"])
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
        source_versions=source_versions,
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
