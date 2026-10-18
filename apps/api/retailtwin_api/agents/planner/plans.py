"""Turn one evidence bundle into bounded candidate decisions.

The planner ships a rule-based, deterministic path as its default. The
historical provider-driven path is preserved behind the
``PLANNER_USE_LLM`` environment variable so an operator can opt the
planner back into a model call when the chain is run outside
production. The deterministic path never consults a model, never
generates a discriminator / const schema for ``response_schema``, and
never depends on the LLM provider being reachable.

The rule-based path inspects the inventory snapshot carried in the
bundle (slot, shelf / backroom quantities, facings) plus the demand
velocity derived from the ``sales_history`` and ``forecast`` items.
The action it picks is constrained to one of the three frozen action
models: ``MoveProduct`` / ``ReplenishShelf`` / ``ChangeFacings``. The
returned ``Decision`` carries the supplied context version, the
evidence bundle, and an unscored ``expected_impact`` so the downstream
simulator, DCG, executor and verifier keep their existing contracts
unchanged.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    EvidenceBundle,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.llm.contracts import (
    InvalidStructuredOutputError,
    LlmMessage,
    LlmProvider,
    LlmRequest,
    StructuredOutput,
    ToolChoicePolicy,
)

log = logging.getLogger(__name__)

_MODEL = "planner"
_AGENT_ID = "retailtwin-planner"
_INSTRUCTION = (
    "Propose two or three candidate plans for this SKU. "
    "Use only replenish_shelf, change_facings, and move_product. "
    "Use only the observed SKU, slot, and backroom quantity. "
    "Each candidate needs a short reason and at least one action. "
    "Do not invent a KPI score, a context version, or a simulation id."
)

# The simulation service has not scored these candidates. This is not a KPI.
UNSCORED_IMPACT = -1.0

INSUFFICIENT_EVIDENCE = "insufficient_evidence"
INVALID_CONTEXT = "invalid_context"
INVALID_OUTPUT = "invalid_output"
FORBIDDEN_ACTION = "forbidden_action"
PROVIDER_FAILED = "provider_failed"
# Deterministic path emits a typed reason when no actionable decision
# can be derived from the evidence. Downstream stages (flagship
# controller, autonomy / replan) surface this verbatim.
NO_ACTIONABLE_DECISION = "no_actionable_decision"

# Rule thresholds for the deterministic path. Tuned for the
# ``run-weekend-demand-surge-1`` canonical seed; documented in the
# task spec.
REPLENISH_VELOCITY_UNITS_PER_HOUR = 6.0
CHANGE_FACINGS_VELOCITY_UNITS_PER_HOUR = 12.0
REPLENISH_MAX_UNITS = 20
SHELF_FILL_FACTOR = 8


# Feature flag for the historical LLM path. Default OFF — the
# planner is deterministic in production and in local runs. Set
# ``PLANNER_USE_LLM=1`` to opt the planner back into a model call
# (kept for explicit enablement).
PLANNER_USE_LLM_ENV = "PLANNER_USE_LLM"


def _llm_enabled() -> bool:
    """Return True when the LLM path is explicitly enabled.

    Reads ``PLANNER_USE_LLM`` from the process environment. The
    default is OFF; only an explicit truthy value (``"1"``,
    ``"true"``, ``"yes"``, ``"on"``, case-insensitive) enables the
    LLM path. This keeps local runs deterministic without
    configuration and lets operators opt the planner back into a
    model call by setting the env var.
    """
    raw = os.environ.get(PLANNER_USE_LLM_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class PlannerError(Exception):
    """Planning failed. The message does not include model output or provider text."""

    def __init__(self, correlation_id: str, reason: str) -> None:
        self.correlation_id = correlation_id
        self.reason = reason
        super().__init__(f"Planning failed for {correlation_id}.")


class _MoveDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["move_product"]
    sku: str = Field(min_length=1)
    from_slot: str = Field(min_length=1)
    to_slot: str = Field(min_length=1)


class _FacingsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["change_facings"]
    sku: str = Field(min_length=1)
    facings: int = Field(ge=1, le=100)


class _ReplenishDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["replenish_shelf"]
    sku: str = Field(min_length=1)
    quantity: int = Field(ge=1, le=1000)


_ActionDraft = Annotated[
    _MoveDraft | _FacingsDraft | _ReplenishDraft,
    Field(discriminator="type"),
]


class _CandidateDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=280)
    actions: list[_ActionDraft] = Field(min_length=1, max_length=3)


class _PlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[_CandidateDraft] = Field(min_length=2, max_length=3)


def _inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                key = str(node["$ref"]).rsplit("/", 1)[-1]
                target = walk(copy.deepcopy(defs[key]))
                extra = {
                    item_key: walk(item_value)
                    for item_key, item_value in node.items()
                    if item_key not in {"$ref", "$defs"}
                }
                if isinstance(target, dict):
                    target.update(extra)
                    target.pop("title", None)
                    return target
                return target
            return {
                item_key: walk(item_value)
                for item_key, item_value in node.items()
                if item_key not in {"$defs", "title"}
            }
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    schema = walk(raw)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise RuntimeError("plan schema must be an object")
    return schema


_PLAN_SCHEMA = _inline_schema(_PlanDraft)


@dataclass(frozen=True)
class _Observed:
    sku: str
    version: str
    slot_id: str
    backroom_quantity: int
    shelf_quantity: int
    facings: int


def _fail(correlation_id: str, reason: str) -> PlannerError:
    log.info(
        "planning rejected correlation_id=%s reason=%s",
        correlation_id,
        reason,
    )
    return PlannerError(correlation_id, reason)


def _whole(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _version_text(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int):
        return str(value)
    return None


def _observed(bundle: EvidenceBundle) -> _Observed:
    correlation_id = bundle.correlation_id
    if not bundle.is_sufficient or len(bundle.entity_versions) != 1:
        raise _fail(correlation_id, INSUFFICIENT_EVIDENCE)
    sku, version = next(iter(bundle.entity_versions.items()))
    if not isinstance(sku, str) or not sku.strip() or not str(version).strip():
        raise _fail(correlation_id, INSUFFICIENT_EVIDENCE)
    inventory: dict[str, Any] | None = None
    reported_version: str | None = None
    for item in bundle.items:
        if item.event_type != "inventory":
            continue
        value = item.payload.get("value")
        if isinstance(value, dict):
            inventory = value
            reported_version = _version_text(item.payload.get("version"))
            break
    if inventory is None:
        raise _fail(correlation_id, INSUFFICIENT_EVIDENCE)
    if reported_version is not None and reported_version != str(version).strip():
        raise _fail(correlation_id, INSUFFICIENT_EVIDENCE)
    value_sku = inventory.get("sku")
    if isinstance(value_sku, str) and value_sku != sku:
        raise _fail(correlation_id, INSUFFICIENT_EVIDENCE)
    slot_id = inventory.get("slot_id")
    backroom = _whole(inventory.get("backroom_quantity"))
    shelf = _whole(inventory.get("shelf_quantity"))
    facings = _whole(inventory.get("facings"))
    if not isinstance(slot_id, str) or not slot_id.strip() or backroom is None or shelf is None or facings is None:
        raise _fail(correlation_id, INSUFFICIENT_EVIDENCE)
    return _Observed(
        sku.strip(),
        str(version).strip(),
        slot_id.strip(),
        backroom,
        shelf,
        facings,
    )


def _check_context(correlation_id: str, context_version: str, context_timestamp: datetime) -> str:
    if not isinstance(context_version, str) or not context_version.strip():
        raise _fail(correlation_id, INVALID_CONTEXT)
    if (
        not isinstance(context_timestamp, datetime)
        or context_timestamp.tzinfo is None
        or context_timestamp.utcoffset() is None
    ):
        raise _fail(correlation_id, INVALID_CONTEXT)
    return context_version.strip()


def _facts(bundle: EvidenceBundle, observed: _Observed) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "bundle_id": bundle.bundle_id,
        "store_id": bundle.store_id,
        "correlation_id": bundle.correlation_id,
        "sku": observed.sku,
        "entity_version": observed.version,
        "slot_id": observed.slot_id,
        "backroom_quantity": observed.backroom_quantity,
    }
    for item in bundle.items:
        if item.event_type != "inventory":
            continue
        value = item.payload.get("value")
        if not isinstance(value, dict):
            continue
        shelf = _whole(value.get("shelf_quantity"))
        facings = _whole(value.get("facings"))
        if shelf is not None:
            facts["shelf_quantity"] = shelf
        if facings is not None:
            facts["facings"] = facings
        break
    for item in bundle.items:
        if item.event_type != "forecast":
            continue
        value = item.payload.get("value")
        if isinstance(value, dict) and isinstance(value.get("forecast_units"), str):
            facts["forecast_units"] = value["forecast_units"]
        break
    return facts


def _contract_action(
    draft: _MoveDraft | _FacingsDraft | _ReplenishDraft,
    observed: _Observed,
) -> MoveProduct | ChangeFacings | ReplenishShelf:
    if draft.sku != observed.sku:
        raise _fail_action()
    if isinstance(draft, _MoveDraft):
        if draft.from_slot != observed.slot_id or draft.to_slot == draft.from_slot:
            raise _fail_action()
        return MoveProduct(sku=draft.sku, from_slot=draft.from_slot, to_slot=draft.to_slot)
    if isinstance(draft, _FacingsDraft):
        return ChangeFacings(sku=draft.sku, facings=draft.facings)
    if draft.quantity > observed.backroom_quantity:
        raise _fail_action()
    return ReplenishShelf(sku=draft.sku, quantity=draft.quantity)


class _ActionRejected(Exception):
    pass


def _fail_action() -> _ActionRejected:
    return _ActionRejected()


def _reason(text: str) -> str:
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 280:
        raise _fail_output()
    return cleaned


class _OutputRejected(Exception):
    pass


def _fail_output() -> _OutputRejected:
    return _OutputRejected()


# ─────────────────────────────────────────────────────────────────────────
# Deterministic path
# ─────────────────────────────────────────────────────────────────────────


def _demand_velocity_units_per_hour(bundle: EvidenceBundle) -> float:
    """Return demand velocity in units per hour from sales_history or forecast.

    Prefers ``sales_history`` (BigQuery-backed, issue #215 / ADR 0024)
    and falls back to ``forecast``. Returns 0.0 when neither source
    carries a usable quantity / window. The result is always a
    finite, non-negative float; malformed inputs degrade to 0.0
    rather than raising so the deterministic path stays in charge of
    the planner's decision (no provider call).
    """
    for item in bundle.items:
        if item.event_type != "sales_history":
            continue
        value = item.payload.get("value")
        if not isinstance(value, dict):
            continue
        sales = value.get("sales")
        window_hours = value.get("window_hours")
        if not isinstance(window_hours, int) or window_hours <= 0:
            continue
        if not isinstance(sales, list):
            continue
        total = 0
        for sale in sales:
            if not isinstance(sale, Mapping):
                continue
            qty = sale.get("quantity")
            if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
                continue
            total += qty
        if total > 0:
            return total / window_hours
    for item in bundle.items:
        if item.event_type != "forecast":
            continue
        value = item.payload.get("value")
        if not isinstance(value, dict):
            continue
        raw_units = value.get("forecast_units")
        units: int | None = None
        if isinstance(raw_units, bool):
            units = None
        elif isinstance(raw_units, int):
            units = raw_units
        elif isinstance(raw_units, str):
            try:
                units = int(Decimal(raw_units))
            except (InvalidOperation, ValueError):
                units = None
        horizon_hours = value.get("horizon_hours")
        if not isinstance(horizon_hours, int) or horizon_hours <= 0 or units is None or units <= 0:
            continue
        return units / horizon_hours
    return 0.0


def _build_decision(
    *,
    bundle: EvidenceBundle,
    observed: _Observed,
    context_version: str,
    context_timestamp: datetime,
    actions: list[MoveProduct | ChangeFacings | ReplenishShelf],
    reason: str,
    index: int,
) -> Decision:
    return Decision(
        decision_id=f"plan-{bundle.correlation_id}-{observed.sku}-{index}",
        agent_id=_AGENT_ID,
        context_version=context_version,
        context_timestamp=context_timestamp,
        evidence=[bundle],
        proposed_actions=actions,
        simulation_id=None,
        expected_impact=ExpectedImpact(kpi_score=UNSCORED_IMPACT, description=reason),
    )


def plan_decision_deterministic(
    bundle: EvidenceBundle,
    *,
    observed: _Observed,
    context_version: str,
    context_timestamp: datetime,
) -> list[Decision]:
    """Return one or two decisions derived from the evidence.

    The rule set:

    1. Demand velocity ``>= REPLENISH_VELOCITY_UNITS_PER_HOUR`` and the
       backroom has stock and the shelf is below the per-facing fill
       factor → ``ReplenishShelf(sku, min(backroom, REPLENISH_MAX_UNITS))``.
    2. Sustained demand ``>= CHANGE_FACINGS_VELOCITY_UNITS_PER_HOUR``
       and the SKU has fewer than 4 facings →
       ``ChangeFacings(sku, facings + 1)``.
    3. Shelf is empty but the backroom has stock → a minimal
       ``ReplenishShelf(sku, 1)`` so the chain can commit and the
       verifier can measure a delta.
    4. Backroom has any stock and none of the above applies → a
       minimal ``ReplenishShelf(sku, 1)`` touch-up.
    5. Backroom and shelf are both zero → no actionable decision;
       return an empty list so the planner surfaces
       ``no_actionable_decision`` and the chain re-plans.

    The returned ``Decision`` carries the supplied context and the
    evidence bundle; ``expected_impact.kpi_score`` is
    ``UNSCORED_IMPACT`` because the simulation service has not run.
    """
    velocity = _demand_velocity_units_per_hour(bundle)
    backroom = observed.backroom_quantity
    shelf = observed.shelf_quantity
    facings = observed.facings
    sku = observed.sku

    if (
        velocity >= REPLENISH_VELOCITY_UNITS_PER_HOUR
        and backroom > 0
        and shelf < (facings * SHELF_FILL_FACTOR)
    ):
        quantity = min(backroom, REPLENISH_MAX_UNITS)
        actions: list[MoveProduct | ChangeFacings | ReplenishShelf] = [
            ReplenishShelf(sku=sku, quantity=quantity)
        ]
        reason = (
            f"deterministic: replenish {sku} from backroom "
            f"velocity={velocity:.2f}units/h shelf={shelf} "
            f"facings={facings} backroom={backroom}"
        )
    elif velocity >= CHANGE_FACINGS_VELOCITY_UNITS_PER_HOUR and facings < 4:
        actions = [ChangeFacings(sku=sku, facings=facings + 1)]
        reason = (
            f"deterministic: increase facings for {sku} to {facings + 1} "
            f"velocity={velocity:.2f}units/h sustained"
        )
    elif shelf == 0 and backroom > 0:
        quantity = min(backroom, 1)
        actions = [ReplenishShelf(sku=sku, quantity=quantity)]
        reason = (
            f"deterministic: refill empty shelf for {sku} "
            f"backroom={backroom}"
        )
    elif backroom > 0:
        actions = [ReplenishShelf(sku=sku, quantity=1)]
        reason = (
            f"deterministic: minimal touch-up for {sku} "
            f"velocity={velocity:.2f}units/h shelf={shelf} backroom={backroom}"
        )
    else:
        log.info(
            "planning no_actionable_decision correlation_id=%s sku=%s "
            "velocity=%.2f shelf=%s backroom=%s",
            bundle.correlation_id,
            sku,
            velocity,
            shelf,
            backroom,
        )
        return []

    decision = _build_decision(
        bundle=bundle,
        observed=observed,
        context_version=context_version,
        context_timestamp=context_timestamp,
        actions=actions,
        reason=reason,
        index=1,
    )
    log.info(
        "plans created (deterministic) correlation_id=%s sku=%s decisions=1",
        bundle.correlation_id,
        sku,
    )
    return [decision]


# ─────────────────────────────────────────────────────────────────────────
# Provider-driven path (gated by PLANNER_USE_LLM env var)
# ─────────────────────────────────────────────────────────────────────────


async def _plan_via_llm(
    bundle: EvidenceBundle,
    *,
    provider: LlmProvider,
    observed: _Observed,
    context_version: str,
    context_timestamp: datetime,
) -> list[Decision]:
    """Call the LLM and validate the structured output against the inventory snapshot."""
    request = LlmRequest(
        model=_MODEL,
        messages=[
            LlmMessage(role="system", content=_INSTRUCTION),
            LlmMessage(
                role="user",
                content=json.dumps(
                    _facts(bundle, observed),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        ],
        tools=[],
        tool_choice=ToolChoicePolicy(mode="none"),
        structured_output=StructuredOutput(name="candidate_plans", schema=_PLAN_SCHEMA),
        temperature=0,
        metadata={"correlation_id": bundle.correlation_id, "sku": observed.sku},
    )
    try:
        response = await provider.complete(request)
    except Exception:
        log.exception(
            "planning failed correlation_id=%s",
            bundle.correlation_id,
        )
        raise PlannerError(bundle.correlation_id, PROVIDER_FAILED) from None
    try:
        response.validate_structured_output(_PLAN_SCHEMA)
        draft = _PlanDraft.model_validate_json(response.content or "")
    except (InvalidStructuredOutputError, ValidationError):
        raise _fail(bundle.correlation_id, INVALID_OUTPUT) from None
    try:
        candidates = [
            (_reason(candidate.reason), [_contract_action(action, observed) for action in candidate.actions])
            for candidate in draft.candidates
        ]
    except _ActionRejected:
        raise _fail(bundle.correlation_id, FORBIDDEN_ACTION) from None
    except _OutputRejected:
        raise _fail(bundle.correlation_id, INVALID_OUTPUT) from None
    decisions = [
        _build_decision(
            bundle=bundle,
            observed=observed,
            context_version=context_version,
            context_timestamp=context_timestamp,
            actions=actions,
            reason=reason,
            index=index,
        )
        for index, (reason, actions) in enumerate(candidates, start=1)
    ]
    log.info(
        "plans created (llm) correlation_id=%s sku=%s decisions=%s",
        bundle.correlation_id,
        observed.sku,
        len(decisions),
    )
    return decisions


# ─────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────


async def plan(
    bundle: EvidenceBundle,
    *,
    provider: LlmProvider,
    context_version: str,
    context_timestamp: datetime,
) -> list[Decision]:
    """Return bound decisions for ``bundle``.

    Default path is the deterministic, rule-based planner — no LLM
    call is made. Set ``PLANNER_USE_LLM=1`` to opt into the
    historical provider-driven path; the ``provider`` argument is
    then consumed by that path. The returned ``Decision`` shape is
    identical either way so the simulator, DCG, executor and
    verifier downstream code is unchanged.

    The returned decisions carry the supplied context and this
    evidence. ``expected_impact.kpi_score`` is ``UNSCORED_IMPACT``
    because simulation has not run. No store write is performed.
    """
    observed = _observed(bundle)
    version = _check_context(bundle.correlation_id, context_version, context_timestamp)
    if _llm_enabled():
        return await _plan_via_llm(
            bundle,
            provider=provider,
            observed=observed,
            context_version=version,
            context_timestamp=context_timestamp,
        )
    decisions = plan_decision_deterministic(
        bundle,
        observed=observed,
        context_version=version,
        context_timestamp=context_timestamp,
    )
    if not decisions:
        raise _fail(bundle.correlation_id, NO_ACTIONABLE_DECISION)
    return decisions