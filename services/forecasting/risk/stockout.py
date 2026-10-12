"""Deterministic stockout risk for one SKU.

The rate is observed units per hour. A forecast may only raise that rate.
The result is evidence. It does not read the Live Twin and it does not change it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

FORMULA_ID = "stockout-risk-v1"
DEFAULT_HORIZON_HOURS = Decimal("4")
HIGH_DEMAND_UNITS_PER_HOUR = Decimal("18.25")
_CENT = Decimal("0.01")

ASSUMPTIONS: tuple[str, ...] = (
    "Demand rate is the observed sales velocity in units per hour.",
    "A forecast can only raise that rate. A missing or lower forecast is ignored.",
    "Units needed equal the demand rate times the horizon. The default horizon is 4 hours.",
    "Shortfall is units needed minus shelf quantity, and it is never negative.",
    "Replenishment is the lesser of the shortfall and the backroom quantity.",
    "High demand means at least 18.25 units per hour, the Saturday rate of the weekend demand surge.",
    "A zero demand rate does not deplete the shelf. An empty shelf with no demand is not a stockout.",
    "An empty shelf with demand is a stockout now, even when the backroom can refill the horizon.",
)


class StockoutRiskError(Exception):
    """The stockout inputs cannot be calculated."""


RiskLevel = Literal["normal", "near_stockout", "stockout"]


@dataclass(frozen=True)
class StockoutInputs:
    store_id: str
    sku: str
    shelf_quantity: int
    backroom_quantity: int
    sales_velocity_units_per_hour: Decimal
    observed_at: datetime
    context_version: str
    correlation_id: str
    horizon_hours: Decimal = DEFAULT_HORIZON_HOURS
    forecast_units_per_hour: Decimal | None = None


@dataclass(frozen=True)
class StockoutRisk:
    formula_id: str
    store_id: str
    sku: str
    correlation_id: str
    context_version: str
    observed_at: str
    horizon_hours: str
    shelf_quantity: int
    backroom_quantity: int
    sales_velocity_units_per_hour: str
    forecast_units_per_hour: str | None
    demand_units_per_hour: str
    units_needed: str
    shelf_hours_of_cover: str | None
    shortfall_units: str
    replenishment_units: str
    uncovered_units: str
    level: RiskLevel
    backroom_covers_horizon: bool
    high_demand: bool
    assumptions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "formula_id": self.formula_id,
            "store_id": self.store_id,
            "sku": self.sku,
            "correlation_id": self.correlation_id,
            "context_version": self.context_version,
            "observed_at": self.observed_at,
            "horizon_hours": self.horizon_hours,
            "shelf_quantity": self.shelf_quantity,
            "backroom_quantity": self.backroom_quantity,
            "sales_velocity_units_per_hour": self.sales_velocity_units_per_hour,
            "forecast_units_per_hour": self.forecast_units_per_hour,
            "demand_units_per_hour": self.demand_units_per_hour,
            "units_needed": self.units_needed,
            "shelf_hours_of_cover": self.shelf_hours_of_cover,
            "shortfall_units": self.shortfall_units,
            "replenishment_units": self.replenishment_units,
            "uncovered_units": self.uncovered_units,
            "level": self.level,
            "backroom_covers_horizon": self.backroom_covers_horizon,
            "high_demand": self.high_demand,
            "assumptions": list(self.assumptions),
        }


def calculate_stockout_risk(inputs: StockoutInputs) -> StockoutRisk:
    """Return stockout evidence for one observed shelf."""

    store_id = _text_id("store_id", inputs.store_id)
    sku = _text_id("sku", inputs.sku)
    context_version = _text_id("context_version", inputs.context_version)
    correlation_id = _text_id("correlation_id", inputs.correlation_id)
    shelf_quantity = _count("shelf_quantity", inputs.shelf_quantity)
    backroom_quantity = _count("backroom_quantity", inputs.backroom_quantity)
    velocity = _rate("sales_velocity_units_per_hour", inputs.sales_velocity_units_per_hour)
    horizon = _rate("horizon_hours", inputs.horizon_hours, allow_zero=False)
    forecast = inputs.forecast_units_per_hour
    if forecast is not None:
        forecast = _rate("forecast_units_per_hour", forecast)
    observed_at = _timestamp(inputs.observed_at)

    demand = velocity if forecast is None or forecast <= velocity else forecast
    units_needed = demand * horizon
    shortfall = units_needed - Decimal(shelf_quantity)
    if shortfall < 0:
        shortfall = Decimal(0)
    replenishment = min(Decimal(backroom_quantity), shortfall)
    uncovered = shortfall - replenishment
    if demand == 0:
        shelf_hours = None
        level: RiskLevel = "normal"
    else:
        shelf_hours = Decimal(shelf_quantity) / demand
        if shelf_quantity == 0:
            level = "stockout"
        elif uncovered > 0:
            level = "near_stockout"
        else:
            level = "normal"

    return StockoutRisk(
        formula_id=FORMULA_ID,
        store_id=store_id,
        sku=sku,
        correlation_id=correlation_id,
        context_version=context_version,
        observed_at=observed_at,
        horizon_hours=_text(horizon),
        shelf_quantity=shelf_quantity,
        backroom_quantity=backroom_quantity,
        sales_velocity_units_per_hour=_text(velocity),
        forecast_units_per_hour=None if forecast is None else _text(forecast),
        demand_units_per_hour=_text(demand),
        units_needed=_text(units_needed),
        shelf_hours_of_cover=None if shelf_hours is None else _text(shelf_hours),
        shortfall_units=_text(shortfall),
        replenishment_units=_text(replenishment),
        uncovered_units=_text(uncovered),
        level=level,
        backroom_covers_horizon=shortfall > 0 and uncovered == 0,
        high_demand=demand >= HIGH_DEMAND_UNITS_PER_HOUR,
        assumptions=ASSUMPTIONS,
    )


def _count(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StockoutRiskError(f"{name} must be a non-negative integer.")
    return value


def _rate(name: str, value: object, allow_zero: bool = True) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise StockoutRiskError(f"{name} must be a finite decimal.")
    if value < 0 or (value == 0 and not allow_zero):
        raise StockoutRiskError(f"{name} must be greater than zero." if not allow_zero else f"{name} cannot be negative.")
    return value


def _text_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StockoutRiskError(f"{name} is required.")
    return value.strip()


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StockoutRiskError("observed_at needs a timezone.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Decimal) -> str:
    rendered = format(value.quantize(_CENT, rounding=ROUND_HALF_UP), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def schema_required(schema: Mapping[str, object]) -> tuple[str, ...]:
    required = schema.get("required")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise StockoutRiskError("Stockout schema has no required list.")
    return tuple(required)
