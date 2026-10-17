"""Deterministic simulation KPI evaluator.

It clones a snapshot, applies candidate actions, and scores the clone.
It does not read or change the Live Twin.

Issue #215 ([P0][DATA-AI]) commits each scored candidate to carry the
``evaluator_version`` of the demand evidence it was scored against. The
demand evidence is the canonical BigQuery ``retailtwin.sales_events``
view threaded through the Investigator's ``get_sales_history`` port
(ADR 0024 / ADR 0005); its ``version`` field is a deterministic
sha256[16] digest of ``query_window`` + ``source_watermark`` +
``data_lineage`` + ``content_digest`` (sha256 over the returned rows),
so two distinct BigQuery jobs returning the same rows reproduce the
same ``version``. When the demand evidence is unavailable the
``evaluator_version`` is ``"none"`` so the result still round-trips
deterministically.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Union

from risk.stockout import StockoutInputs, StockoutRisk, StockoutRiskError, calculate_stockout_risk

FORMULA_ID = "simulation-kpi-v1"
ALPHA = Decimal("1")
BETA = Decimal("0")
GAMMA = Decimal("1")
DELTA = Decimal("1")
EPSILON = Decimal("1")
_CENT = Decimal("0.01")

# Version string when no demand evidence was threaded through (tests
# that pre-date issue #215 / unit tests that don't care about the
# BigQuery reader still pass this string).
NO_DEMAND_EVIDENCE_VERSION = "none"

ASSUMPTIONS: tuple[str, ...] = (
    "Actions are applied to a clone of the simulation snapshot. The Live Twin is not read or changed.",
    "Stockout risk comes from stockout-risk-v1 on the clone. An empty shelf with demand scores 1.",
    "Service level is the share of horizon demand the shelf can cover after the actions, and it ignores stock that is still in the backroom.",
    "Revenue benefit is the extra shelf units the clone can sell, divided by horizon demand. Margin benefit is 0.",
    "Movement cost is replenished units, plus each facing changed, plus 1 for a slot move, divided by horizon demand.",
    "business_score uses the displayed hundredths: 1*revenue_benefit + 0*margin_benefit + 1*service_level - 1*stockout_risk - 1*movement_cost.",
    "A repeated candidate id for one simulation_id must reproduce the stored result.",
    "evaluator_version is the version of the demand evidence the candidate was scored against (a deterministic sha256[16] digest of query_window + source_watermark + data_lineage + content_digest for ``retailtwin.sales_events``, ``none`` when no demand evidence is threaded).",
)


class KpiError(Exception):
    """The candidate cannot be scored."""


@dataclass(frozen=True)
class SlotState:
    sku: str
    slot_id: str
    shelf_quantity: int
    backroom_quantity: int
    facings: int
    sales_velocity_units_per_hour: Decimal
    price: Decimal = Decimal("0")
    forecast_units_per_hour: Decimal | None = None


@dataclass(frozen=True)
class SimulationSnapshot:
    simulation_id: str
    store_id: str
    context_version: str
    correlation_id: str
    observed_at: datetime
    slots: tuple[SlotState, ...]


@dataclass(frozen=True)
class MoveProduct:
    sku: str
    from_slot: str
    to_slot: str


@dataclass(frozen=True)
class ChangeFacings:
    sku: str
    facings: int


@dataclass(frozen=True)
class ReplenishShelf:
    sku: str
    quantity: int


Action = Union[MoveProduct, ChangeFacings, ReplenishShelf]


@dataclass(frozen=True)
class KpiResult:
    formula_id: str
    simulation_id: str
    candidate_id: str
    store_id: str
    correlation_id: str
    context_version: str
    observed_at: str
    stockout_risk: str
    service_level: str
    movement_cost: str
    revenue_benefit: str
    margin_benefit: str
    business_score: str
    movement_units: str
    assumptions: tuple[str, ...]
    # Version of the demand evidence the candidate was scored against
    # (issue #215). Set by ``evaluate_candidate(..., evaluator_version=...)``
    # so a BigQuery-backed ``get_sales_history`` job id round-trips on
    # every result. ``NO_DEMAND_EVIDENCE_VERSION`` when none is threaded.
    evaluator_version: str = NO_DEMAND_EVIDENCE_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "formula_id": self.formula_id,
            "simulation_id": self.simulation_id,
            "candidate_id": self.candidate_id,
            "store_id": self.store_id,
            "correlation_id": self.correlation_id,
            "context_version": self.context_version,
            "observed_at": self.observed_at,
            "stockout_risk": self.stockout_risk,
            "service_level": self.service_level,
            "movement_cost": self.movement_cost,
            "revenue_benefit": self.revenue_benefit,
            "margin_benefit": self.margin_benefit,
            "business_score": self.business_score,
            "movement_units": self.movement_units,
            "evaluator_version": self.evaluator_version,
            "assumptions": list(self.assumptions),
        }


class KpiLedger:
    """In-memory results for one process. The key is simulation_id plus candidate_id."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], KpiResult] = {}

    def evaluate(
        self,
        snapshot: SimulationSnapshot,
        candidate_id: str,
        actions: Sequence[Action],
        *,
        evaluator_version: str = NO_DEMAND_EVIDENCE_VERSION,
    ) -> KpiResult:
        result = evaluate_candidate(
            snapshot,
            candidate_id,
            actions,
            evaluator_version=evaluator_version,
        )
        key = (result.simulation_id, result.candidate_id)
        stored = self._rows.get(key)
        if stored is None:
            self._rows[key] = result
            return result
        if stored != result:
            raise KpiError(
                f"{result.simulation_id} already has a different result for {result.candidate_id}."
            )
        return stored

    def results_for(self, simulation_id: str) -> tuple[KpiResult, ...]:
        name = _text_id("simulation_id", simulation_id)
        return tuple(result for (stored_id, _), result in self._rows.items() if stored_id == name)


def evaluate_candidate(
    snapshot: SimulationSnapshot,
    candidate_id: str,
    actions: Sequence[Action],
    *,
    evaluator_version: str = NO_DEMAND_EVIDENCE_VERSION,
) -> KpiResult:
    """Score one candidate. The same snapshot and actions always return the same result.

    ``evaluator_version`` is the demand-evidence version (issue #215 /
    ADR 0024) the candidate was scored against — typically the BigQuery
    job id surfaced by ``read_sales_history``. The default
    ``NO_DEMAND_EVIDENCE_VERSION`` keeps the historic test surface
    unchanged for callers that pre-date the BigQuery wiring.
    """

    checked = _snapshot(snapshot)
    name = _text_id("candidate_id", candidate_id)
    if isinstance(actions, (str, bytes)) or not isinstance(actions, Sequence):
        raise KpiError("actions must be a sequence.")
    demand_evidence_version = _request_evaluator_version(evaluator_version)
    before = {slot.sku: slot for slot in checked.slots}
    slots, movement_units = _apply(before, tuple(actions))
    ordered = sorted(slots.values(), key=lambda item: item.sku)
    risks = [_risk(checked, slot) for slot in ordered]
    needed = [_needed(risk) for risk in risks]
    total_needed = sum(needed, Decimal(0))
    if total_needed == 0:
        stockout_risk = Decimal(0)
        service_level = Decimal(1)
        revenue_benefit = Decimal(0)
        movement_cost = Decimal(0) if movement_units == 0 else Decimal(1)
    else:
        stockout_risk = sum(
            (_risk_fraction(risk) * units for risk, units in zip(risks, needed)),
            Decimal(0),
        ) / total_needed
        service_level = sum(
            (_service(slot, units) * units for slot, units in zip(ordered, needed)),
            Decimal(0),
        ) / total_needed
        revenue_benefit = sum(
            (_extra_sellable(before[slot.sku], slot, units) for slot, units in zip(ordered, needed)),
            Decimal(0),
        ) / total_needed
        movement_cost = min(Decimal(1), Decimal(movement_units) / total_needed)
    stockout_text = _text(stockout_risk)
    service_text = _text(service_level)
    revenue_text = _text(revenue_benefit)
    movement_text = _text(movement_cost)
    score = (
        ALPHA * Decimal(revenue_text)
        + BETA * Decimal(0)
        + GAMMA * Decimal(service_text)
        - DELTA * Decimal(stockout_text)
        - EPSILON * Decimal(movement_text)
    )
    return KpiResult(
        formula_id=FORMULA_ID,
        simulation_id=checked.simulation_id,
        candidate_id=name,
        store_id=checked.store_id,
        correlation_id=checked.correlation_id,
        context_version=checked.context_version,
        observed_at=_timestamp(checked.observed_at),
        stockout_risk=stockout_text,
        service_level=service_text,
        movement_cost=movement_text,
        revenue_benefit=revenue_text,
        margin_benefit="0",
        business_score=_text(score),
        movement_units=str(movement_units),
        evaluator_version=demand_evidence_version,
        assumptions=ASSUMPTIONS,
    )


def schema_required(schema: Mapping[str, object]) -> tuple[str, ...]:
    required = schema.get("required")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise KpiError("KPI schema has no required list.")
    return tuple(required)


def _apply(before: dict[str, SlotState], actions: tuple[Action, ...]) -> tuple[dict[str, SlotState], int]:
    slots = dict(before)
    movement = 0
    for action in actions:
        if isinstance(action, ReplenishShelf):
            slot = _slot(slots, action.sku, "replenish_shelf")
            quantity = _count("quantity", action.quantity, minimum=1)
            if quantity > slot.backroom_quantity:
                raise KpiError(f"{slot.sku} backroom cannot supply {quantity}.")
            slots[slot.sku] = replace(
                slot,
                shelf_quantity=slot.shelf_quantity + quantity,
                backroom_quantity=slot.backroom_quantity - quantity,
            )
            movement += quantity
            continue
        if isinstance(action, ChangeFacings):
            slot = _slot(slots, action.sku, "change_facings")
            facings = _count("facings", action.facings, minimum=1)
            movement += abs(facings - slot.facings)
            slots[slot.sku] = replace(slot, facings=facings)
            continue
        if isinstance(action, MoveProduct):
            slot = _slot(slots, action.sku, "move_product")
            origin = _text_id("from_slot", action.from_slot)
            destination = _text_id("to_slot", action.to_slot)
            if slot.slot_id != origin:
                raise KpiError(f"{slot.sku} is in {slot.slot_id}, not {origin}.")
            if origin == destination:
                raise KpiError(f"{slot.sku} is already in {destination}.")
            if any(other.slot_id == destination for other in slots.values()):
                raise KpiError(f"{destination} is occupied.")
            slots[slot.sku] = replace(slot, slot_id=destination)
            movement += 1
            continue
        raise KpiError("Unknown action.")
    return slots, movement


def _risk(snapshot: SimulationSnapshot, slot: SlotState) -> StockoutRisk:
    try:
        return calculate_stockout_risk(
            StockoutInputs(
                store_id=snapshot.store_id,
                sku=slot.sku,
                shelf_quantity=slot.shelf_quantity,
                backroom_quantity=slot.backroom_quantity,
                sales_velocity_units_per_hour=slot.sales_velocity_units_per_hour,
                observed_at=snapshot.observed_at,
                context_version=snapshot.context_version,
                correlation_id=snapshot.correlation_id,
                forecast_units_per_hour=slot.forecast_units_per_hour,
            )
        )
    except StockoutRiskError as exc:
        raise KpiError(str(exc)) from exc


def _needed(risk: StockoutRisk) -> Decimal:
    return Decimal(risk.units_needed)


def _risk_fraction(risk: StockoutRisk) -> Decimal:
    needed = _needed(risk)
    if needed == 0:
        return Decimal(0)
    if risk.level == "stockout":
        return Decimal(1)
    return Decimal(risk.uncovered_units) / needed


def _service(slot: SlotState, needed: Decimal) -> Decimal:
    if needed == 0:
        return Decimal(1)
    if slot.shelf_quantity == 0:
        return Decimal(0)
    covered = Decimal(slot.shelf_quantity) / needed
    if covered > 1:
        return Decimal(1)
    return covered


def _extra_sellable(before: SlotState, after: SlotState, needed: Decimal) -> Decimal:
    if needed == 0:
        return Decimal(0)
    sold_before = min(Decimal(before.shelf_quantity), needed)
    sold_after = min(Decimal(after.shelf_quantity), needed)
    extra = sold_after - sold_before
    if extra < 0:
        return Decimal(0)
    return extra


def _snapshot(snapshot: SimulationSnapshot) -> SimulationSnapshot:
    if not isinstance(snapshot, SimulationSnapshot):
        raise KpiError("snapshot must be a simulation snapshot.")
    simulation_id = _text_id("simulation_id", snapshot.simulation_id)
    store_id = _text_id("store_id", snapshot.store_id)
    context_version = _text_id("context_version", snapshot.context_version)
    correlation_id = _text_id("correlation_id", snapshot.correlation_id)
    if not isinstance(snapshot.observed_at, datetime):
        raise KpiError("observed_at needs a timezone.")
    if not isinstance(snapshot.slots, tuple) or not snapshot.slots:
        raise KpiError("snapshot needs at least one slot.")
    seen_sku: set[str] = set()
    seen_slot: set[str] = set()
    slots: list[SlotState] = []
    for slot in snapshot.slots:
        if not isinstance(slot, SlotState):
            raise KpiError("snapshot slot is not a slot.")
        sku = _text_id("sku", slot.sku)
        slot_id = _text_id("slot_id", slot.slot_id)
        if sku in seen_sku:
            raise KpiError(f"{sku} is on more than one slot.")
        if slot_id in seen_slot:
            raise KpiError(f"{slot_id} is used more than once.")
        seen_sku.add(sku)
        seen_slot.add(slot_id)
        slots.append(
            replace(
                slot,
                sku=sku,
                slot_id=slot_id,
                shelf_quantity=_count("shelf_quantity", slot.shelf_quantity, minimum=0),
                backroom_quantity=_count("backroom_quantity", slot.backroom_quantity, minimum=0),
                facings=_count("facings", slot.facings, minimum=1),
                sales_velocity_units_per_hour=_rate(
                    "sales_velocity_units_per_hour",
                    slot.sales_velocity_units_per_hour,
                ),
                price=_rate("price", slot.price),
            )
        )
    return replace(
        snapshot,
        simulation_id=simulation_id,
        store_id=store_id,
        context_version=context_version,
        correlation_id=correlation_id,
        slots=tuple(slots),
    )


def _slot(slots: dict[str, SlotState], sku: object, action: str) -> SlotState:
    name = _text_id("sku", sku)
    slot = slots.get(name)
    if slot is None:
        raise KpiError(f"{action} has no slot for {name}.")
    return slot


def _count(name: str, value: object, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise KpiError(f"{name} must be an integer of at least {minimum}.")
    return value


def _rate(name: str, value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise KpiError(f"{name} must be a non-negative decimal.")
    return value


def _text_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KpiError(f"{name} is required.")
    return value.strip()


def _request_evaluator_version(value: object) -> str:
    """Validate the demand-evidence ``evaluator_version`` argument.

    The default value is ``NO_DEMAND_EVIDENCE_VERSION`` so callers that
    pre-date issue #215 still work; any other non-empty string is
    passed through verbatim so the BigQuery job id (or a deterministic
    digest, see ``bigquery_sales_history._safe_job_id``) round-trips.
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise KpiError("evaluator_version must be a string.")
    stripped = value.strip()
    if not stripped:
        raise KpiError("evaluator_version is required.")
    return stripped


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise KpiError("observed_at needs a timezone.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Decimal) -> str:
    rendered = format(value.quantize(_CENT, rounding=ROUND_HALF_UP), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"
