"""Deterministic demand forecast for one SKU.

BigQuery ML is not called. A model may be supplied by the caller. When that
path is disabled or the model is unavailable, the next horizon repeats the
latest window of sales. The Live Twin is not read or changed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

FORMULA_ID = "forecast-demand-v1"
FALLBACK_METHOD = "window-rate"
DEFAULT_HORIZON_HOURS = Decimal("4")
_MAX_HORIZON_HOURS = Decimal("24")
_DAY = timedelta(days=1)
_CENT = Decimal("0.01")

ASSUMPTIONS: tuple[str, ...] = (
    "The forecast does not read or change the Live Twin and does not call BigQuery.",
    "With ML disabled or unavailable, forecast units repeat the units sold in the latest window.",
    "The latest window ends at the latest sale. The prior window is the same interval one day earlier.",
    "Direction is up, down, or flat from those windows, or unavailable when the prior window has no sales.",
    "A repeated event_id counts once. One forecast uses one store, one SKU, and one correlation_id.",
    "A supplied model may replace the unit total. ForecastModelError keeps the window rate.",
)


class ForecastError(Exception):
    """The sales series cannot be forecast."""


class ForecastModelError(Exception):
    """The supplied model cannot produce a forecast."""


class ForecastModel(Protocol):
    """Optional replacement for the window rate. This package does not call BigQuery."""

    method_id: str

    def predict(
        self,
        sku: str,
        horizon_hours: Decimal,
        sales: tuple["SaleObservation", ...],
    ) -> Decimal:
        """Return forecast units over the horizon."""


@dataclass(frozen=True)
class SaleObservation:
    event_id: str
    store_id: str
    sku: str
    quantity: int
    occurred_at: datetime
    correlation_id: str


@dataclass(frozen=True)
class ForecastInputs:
    store_id: str
    sku: str
    correlation_id: str
    generated_at: datetime
    sales: Sequence[SaleObservation]
    horizon_hours: Decimal = DEFAULT_HORIZON_HOURS
    use_ml: bool = False
    model: ForecastModel | None = None


@dataclass(frozen=True)
class ForecastDemand:
    formula_id: str
    store_id: str
    sku: str
    correlation_id: str
    generated_at: str
    horizon_hours: str
    forecast_units: str
    units_per_hour: str
    method_id: str
    ml_used: bool
    ml_status: str
    direction: str
    increase: str | None
    observed_units: str
    prior_units: str
    latest_window_start: str
    latest_window_end: str
    prior_window_start: str
    prior_window_end: str
    event_ids: tuple[str, ...]
    assumptions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "formula_id": self.formula_id,
            "store_id": self.store_id,
            "sku": self.sku,
            "correlation_id": self.correlation_id,
            "generated_at": self.generated_at,
            "horizon_hours": self.horizon_hours,
            "forecast_units": self.forecast_units,
            "units_per_hour": self.units_per_hour,
            "method_id": self.method_id,
            "ml_used": self.ml_used,
            "ml_status": self.ml_status,
            "direction": self.direction,
            "increase": self.increase,
            "observed_units": self.observed_units,
            "prior_units": self.prior_units,
            "latest_window_start": self.latest_window_start,
            "latest_window_end": self.latest_window_end,
            "prior_window_start": self.prior_window_start,
            "prior_window_end": self.prior_window_end,
            "event_ids": list(self.event_ids),
            "assumptions": list(self.assumptions),
        }


def forecast_demand(inputs: ForecastInputs) -> ForecastDemand:
    """Forecast one SKU. The same inputs always return the same result."""

    if not isinstance(inputs, ForecastInputs):
        raise ForecastError("inputs must be a forecast request.")
    store_id = _text_id("store_id", inputs.store_id)
    sku = _text_id("sku", inputs.sku)
    correlation_id = _text_id("correlation_id", inputs.correlation_id)
    horizon = _horizon(inputs.horizon_hours)
    generated_at = _timestamp("generated_at", inputs.generated_at)
    use_ml = _flag(inputs.use_ml)
    sales = _sales(inputs.sales, store_id, sku, correlation_id)
    latest_end = max(sale.occurred_at for sale in sales)
    latest_start = latest_end - _hours(horizon)
    prior_end = latest_end - _DAY
    prior_start = prior_end - _hours(horizon)
    latest = tuple(sale for sale in sales if latest_start <= sale.occurred_at <= latest_end)
    prior = tuple(
        sale
        for sale in sales
        if prior_start <= sale.occurred_at <= prior_end and sale not in latest
    )
    observed = sum(sale.quantity for sale in latest)
    previous = sum(sale.quantity for sale in prior)
    direction, increase = _direction(observed, previous)
    fallback_units = Decimal(observed)
    units, method_id, ml_used, ml_status = _predict(
        inputs.model,
        use_ml,
        sku,
        horizon,
        sales,
        fallback_units,
    )
    evidence = tuple(sale.event_id for sale in sales if sale in latest or sale in prior)
    return ForecastDemand(
        formula_id=FORMULA_ID,
        store_id=store_id,
        sku=sku,
        correlation_id=correlation_id,
        generated_at=generated_at,
        horizon_hours=_text(horizon),
        forecast_units=_text(units),
        units_per_hour=_text(units / horizon),
        method_id=method_id,
        ml_used=ml_used,
        ml_status=ml_status,
        direction=direction,
        increase=None if increase is None else _text(increase),
        observed_units=str(observed),
        prior_units=str(previous),
        latest_window_start=_timestamp("latest_window_start", latest_start),
        latest_window_end=_timestamp("latest_window_end", latest_end),
        prior_window_start=_timestamp("prior_window_start", prior_start),
        prior_window_end=_timestamp("prior_window_end", prior_end),
        event_ids=evidence,
        assumptions=ASSUMPTIONS,
    )


def _predict(
    model: ForecastModel | None,
    use_ml: bool,
    sku: str,
    horizon: Decimal,
    sales: tuple[SaleObservation, ...],
    fallback_units: Decimal,
) -> tuple[Decimal, str, bool, str]:
    if not use_ml:
        return fallback_units, FALLBACK_METHOD, False, "disabled"
    if model is None:
        return fallback_units, FALLBACK_METHOD, False, "unavailable"
    try:
        raw = model.predict(sku, horizon, sales)
    except ForecastModelError:
        return fallback_units, FALLBACK_METHOD, False, "unavailable"
    if isinstance(raw, bool) or not isinstance(raw, Decimal) or not raw.is_finite() or raw < 0:
        raise ForecastError("model forecast units must be a non-negative decimal.")
    method_id = getattr(model, "method_id", None)
    if not isinstance(method_id, str) or not method_id.strip():
        raise ForecastError("model method_id is required.")
    return raw, method_id.strip(), True, "used"


def _sales(
    sales: object,
    store_id: str,
    sku: str,
    correlation_id: str,
) -> tuple[SaleObservation, ...]:
    if isinstance(sales, (str, bytes)) or not isinstance(sales, Sequence):
        raise ForecastError("sales must be a sequence.")
    seen: dict[str, SaleObservation] = {}
    for sale in sales:
        if not isinstance(sale, SaleObservation):
            raise ForecastError("sales entry is not a sale.")
        if _text_id("store_id", sale.store_id) != store_id or _text_id("sku", sale.sku) != sku:
            continue
        if _text_id("correlation_id", sale.correlation_id) != correlation_id:
            raise ForecastError("sales must share the requested correlation_id.")
        event_id = _text_id("event_id", sale.event_id)
        occurred_at = _aware("occurred_at", sale.occurred_at)
        quantity = _count(sale.quantity)
        checked = SaleObservation(
            event_id=event_id,
            store_id=store_id,
            sku=sku,
            quantity=quantity,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
        )
        previous = seen.get(event_id)
        if previous is None:
            seen[event_id] = checked
            continue
        if previous != checked:
            raise ForecastError(f"{event_id} has two payloads.")
    if not seen:
        raise ForecastError("no sales for this SKU.")
    return tuple(sorted(seen.values(), key=lambda sale: (sale.occurred_at, sale.event_id)))


def _direction(observed: int, previous: int) -> tuple[str, Decimal | None]:
    if previous == 0:
        return "unavailable", None
    change = Decimal(observed - previous) / Decimal(previous)
    if observed > previous:
        return "up", change
    if observed < previous:
        return "down", change
    return "flat", Decimal(0)


def _horizon(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise ForecastError("horizon_hours must be a finite decimal.")
    if value <= 0 or value > _MAX_HORIZON_HOURS:
        raise ForecastError("horizon_hours must be greater than 0 and at most 24.")
    return value


def _hours(value: Decimal) -> timedelta:
    return timedelta(seconds=int(value * Decimal(3600)))


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ForecastError("quantity must be an integer of at least 1.")
    return value


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise ForecastError("use_ml must be true or false.")
    return value


def _text_id(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ForecastError(f"{name} is required.")
    return value.strip()


def _aware(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ForecastError(f"{name} needs a timezone.")
    return value.astimezone(timezone.utc)


def _timestamp(name: str, value: datetime) -> str:
    checked = _aware(name, value)
    return checked.isoformat().replace("+00:00", "Z")


def _text(value: Decimal) -> str:
    rendered = format(value.quantize(_CENT, rounding=ROUND_HALF_UP), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"
