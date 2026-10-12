import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from demand.forecast import (
    ASSUMPTIONS,
    FORMULA_ID,
    ForecastError,
    ForecastInputs,
    ForecastModelError,
    SaleObservation,
    forecast_demand,
)

FIXTURE = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "weekend-demand-surge.json"
GENERATED = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
SCHEMA = Path(__file__).resolve().parents[1] / "demand" / "forecast-demand.schema.json"


class CountingModel:
    def __init__(self, units: Decimal | None = None, fail: bool = False) -> None:
        self.method_id = "bqml-test"
        self.units = Decimal("80") if units is None else units
        self.fail = fail
        self.calls = 0

    def predict(
        self,
        sku: str,
        horizon_hours: Decimal,
        sales: tuple[SaleObservation, ...],
    ) -> Decimal:
        self.calls += 1
        if self.fail:
            raise ForecastModelError("model unavailable")
        return self.units


def weekend_sales() -> tuple[SaleObservation, ...]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sales: list[SaleObservation] = []
    for event in payload["events"]:
        sales.append(
            SaleObservation(
                event_id=event["event_id"],
                store_id=event["store_id"],
                sku=event["sku"],
                quantity=event["quantity"],
                occurred_at=datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")),
                correlation_id=event["correlation_id"],
            )
        )
    return tuple(sales)


def request(sales: tuple[SaleObservation, ...], **kwargs: object) -> ForecastInputs:
    values: dict[str, object] = {
        "store_id": "store-001",
        "sku": "P017",
        "correlation_id": "run-weekend-demand-surge-1",
        "generated_at": GENERATED,
        "sales": sales,
    }
    values.update(kwargs)
    return ForecastInputs(**values)  # type: ignore[arg-type]


def test_weekend_series_forecasts_up() -> None:
    result = forecast_demand(request(weekend_sales()))

    assert result.formula_id == FORMULA_ID
    assert result.forecast_units == "73"
    assert result.units_per_hour == "18.25"
    assert result.horizon_hours == "4"
    assert result.direction == "up"
    assert result.increase == "0.46"
    assert result.observed_units == "73"
    assert result.prior_units == "50"
    assert result.method_id == "window-rate"
    assert result.ml_used is False
    assert result.ml_status == "disabled"
    assert result.generated_at == "2026-10-10T12:00:00Z"
    assert len(result.event_ids) == 13


def test_the_same_series_repeats() -> None:
    sales = weekend_sales()

    assert forecast_demand(request(sales)) == forecast_demand(request(tuple(reversed(sales))))


def test_disabled_ml_does_not_call_the_model() -> None:
    model = CountingModel()
    result = forecast_demand(request(weekend_sales(), model=model, use_ml=False))

    assert model.calls == 0
    assert result.forecast_units == "73"
    assert result.ml_status == "disabled"


def test_an_unavailable_model_keeps_the_window_rate() -> None:
    missing = forecast_demand(request(weekend_sales(), use_ml=True))
    failed = CountingModel(fail=True)
    fallen_back = forecast_demand(request(weekend_sales(), model=failed, use_ml=True))

    assert missing.ml_status == "unavailable"
    assert missing.forecast_units == "73"
    assert missing.method_id == "window-rate"
    assert failed.calls == 1
    assert fallen_back == missing


def test_a_stable_model_replaces_the_unit_total() -> None:
    model = CountingModel(Decimal("80"))
    result = forecast_demand(request(weekend_sales(), model=model, use_ml=True))

    assert model.calls == 1
    assert result.forecast_units == "80"
    assert result.units_per_hour == "20"
    assert result.method_id == "bqml-test"
    assert result.ml_used is True
    assert result.ml_status == "used"
    assert result.direction == "up"
    assert result.observed_units == "73"


def test_one_window_has_no_prior_direction() -> None:
    friday = tuple(sale for sale in weekend_sales() if sale.occurred_at.day == 9)
    result = forecast_demand(request(friday))

    assert result.forecast_units == "50"
    assert result.units_per_hour == "12.5"
    assert result.direction == "unavailable"
    assert result.increase is None
    assert result.prior_units == "0"


def test_a_decline_points_down() -> None:
    start = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
    sales = (
        _sale("evt-down-1", 10, start),
        _sale("evt-down-2", 4, start + timedelta(days=1)),
    )
    result = forecast_demand(request(sales))

    assert result.forecast_units == "4"
    assert result.direction == "down"
    assert result.increase == "-0.6"
    assert result.prior_units == "10"


def test_a_duplicate_event_counts_once() -> None:
    sales = weekend_sales()
    result = forecast_demand(request(sales + (sales[-1],)))

    assert result.observed_units == "73"
    assert result.event_ids.count(sales[-1].event_id) == 1


def test_invalid_inputs_fail() -> None:
    sales = weekend_sales()
    with pytest.raises(ForecastError, match="generated_at"):
        forecast_demand(request(sales, generated_at=datetime(2026, 10, 10, 12, 0)))
    with pytest.raises(ForecastError, match="horizon_hours"):
        forecast_demand(request(sales, horizon_hours=Decimal("0")))
    with pytest.raises(ForecastError, match="at most 24"):
        forecast_demand(request(sales, horizon_hours=Decimal("25")))
    with pytest.raises(ForecastError, match="correlation_id"):
        forecast_demand(
            request(sales + (_sale("evt-other", 1, sales[-1].occurred_at, correlation_id="other"),))
        )
    with pytest.raises(ForecastError, match="two payloads"):
        clash = SaleObservation(
            event_id=sales[0].event_id,
            store_id=sales[0].store_id,
            sku=sales[0].sku,
            quantity=sales[0].quantity + 1,
            occurred_at=sales[0].occurred_at,
            correlation_id=sales[0].correlation_id,
        )
        forecast_demand(request(sales + (clash,)))
    with pytest.raises(ForecastError, match="quantity"):
        forecast_demand(request((_sale("evt-bool", True, sales[-1].occurred_at),)))  # type: ignore[arg-type]
    with pytest.raises(ForecastError, match="no sales"):
        forecast_demand(request(()))
    with pytest.raises(ForecastError, match="non-negative"):
        forecast_demand(request(sales, model=CountingModel(Decimal("-1")), use_ml=True))


def test_evidence_matches_the_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    evidence = forecast_demand(request(weekend_sales())).as_dict()

    assert schema["additionalProperties"] is False
    assert schema["required"] == list(evidence)
    assert evidence["assumptions"] == list(ASSUMPTIONS)
    assert set(evidence) == set(schema["properties"])


def _sale(
    event_id: str,
    quantity: int,
    occurred_at: datetime,
    correlation_id: str = "run-weekend-demand-surge-1",
) -> SaleObservation:
    return SaleObservation(
        event_id=event_id,
        store_id="store-001",
        sku="P017",
        quantity=quantity,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
    )
