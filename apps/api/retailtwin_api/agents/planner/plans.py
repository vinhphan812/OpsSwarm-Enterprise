"""Turn one evidence bundle into bounded candidate decisions.

The provider must return structured candidates. The planner checks those
actions against the frozen action models and the observed evidence, then
binds the context and the evidence itself. The model does not choose the
context version, the evidence, or a KPI score. A rejected action is not
returned and is not sent to simulation.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from datetime import datetime
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
    return _Observed(sku.strip(), str(version).strip(), slot_id.strip(), backroom)


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


async def plan(
    bundle: EvidenceBundle,
    *,
    provider: LlmProvider,
    context_version: str,
    context_timestamp: datetime,
) -> list[Decision]:
    """Return two or three decisions for ``bundle``.

    The returned decisions carry the supplied context and this evidence.
    ``expected_impact.kpi_score`` is ``UNSCORED_IMPACT`` because simulation
    has not run. No store write is performed.
    """

    observed = _observed(bundle)
    version = _check_context(bundle.correlation_id, context_version, context_timestamp)
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
    # Tool calls are not executed. response.content is validated, then only the
    # reason summary and the checked actions are kept.
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
        Decision(
            decision_id=f"plan-{bundle.correlation_id}-{observed.sku}-{index}",
            agent_id=_AGENT_ID,
            context_version=version,
            context_timestamp=context_timestamp,
            evidence=[bundle],
            proposed_actions=actions,
            simulation_id=None,
            expected_impact=ExpectedImpact(kpi_score=UNSCORED_IMPACT, description=reason),
        )
        for index, (reason, actions) in enumerate(candidates, start=1)
    ]
    log.info(
        "plans created correlation_id=%s sku=%s decisions=%s",
        bundle.correlation_id,
        observed.sku,
        len(decisions),
    )
    return decisions
