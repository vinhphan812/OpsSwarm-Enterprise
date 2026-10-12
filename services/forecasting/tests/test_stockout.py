import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from risk.stockout import (
    ASSUMPTIONS,
    FORMULA_ID,
    StockoutInputs,
    StockoutRiskError,
    calculate_stockout_risk,
    schema_required,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "risk" / "stockout-risk.schema.json"
OBSERVED = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


def inputs(**overrides: object) -> StockoutInputs:
    values: dict[str, object] = {
        "store_id": "store-001",
        "sku": "P017",
        "shelf_quantity": 40,
        "backroom_quantity": 10,
        "sales_velocity_units_per_hour": Decimal("2"),
        "observed_at": OBSERVED,
        "context_version": "store-001:v1",
        "correlation_id": "run-weekend-demand-surge-1",
    }
    values.update(overrides)
    return StockoutInputs(**values)  # type: ignore[arg-type]


def test_normal_cover_needs_no_backroom() -> None:
    risk = calculate_stockout_risk(inputs())

    assert risk.level == "normal"
    assert risk.units_needed == "8"
    assert risk.shortfall_units == "0"
    assert risk.uncovered_units == "0"
    assert risk.shelf_hours_of_cover == "20"
    assert risk.backroom_covers_horizon is False
    assert risk.high_demand is False
    assert risk.forecast_units_per_hour is None
    assert risk.formula_id == FORMULA_ID


def test_near_stockout_when_the_backroom_cannot_cover_the_horizon() -> None:
    risk = calculate_stockout_risk(
        inputs(shelf_quantity=2, backroom_quantity=0, sales_velocity_units_per_hour=Decimal("4"))
    )

    assert risk.level == "near_stockout"
    assert risk.units_needed == "16"
    assert risk.shortfall_units == "14"
    assert risk.replenishment_units == "0"
    assert risk.uncovered_units == "14"
    assert risk.shelf_hours_of_cover == "0.5"
    assert risk.backroom_covers_horizon is False
    assert risk.high_demand is False


def test_sufficient_backroom_covers_the_shelf_shortfall() -> None:
    risk = calculate_stockout_risk(
        inputs(shelf_quantity=8, backroom_quantity=54, sales_velocity_units_per_hour=Decimal("4"))
    )

    assert risk.level == "normal"
    assert risk.units_needed == "16"
    assert risk.shortfall_units == "8"
    assert risk.replenishment_units == "8"
    assert risk.uncovered_units == "0"
    assert risk.backroom_covers_horizon is True
    assert risk.high_demand is False


def test_weekend_surge_is_high_demand_and_still_short_after_the_backroom() -> None:
    risk = calculate_stockout_risk(
        inputs(shelf_quantity=8, backroom_quantity=54, sales_velocity_units_per_hour=Decimal("18.25"))
    )

    assert risk.level == "near_stockout"
    assert risk.demand_units_per_hour == "18.25"
    assert risk.units_needed == "73"
    assert risk.shortfall_units == "65"
    assert risk.replenishment_units == "54"
    assert risk.uncovered_units == "11"
    assert risk.shelf_hours_of_cover == "0.44"
    assert risk.high_demand is True
    assert risk.correlation_id == "run-weekend-demand-surge-1"
    assert risk.observed_at == "2026-10-10T08:00:00Z"


def test_the_same_inputs_repeat() -> None:
    assert calculate_stockout_risk(inputs()) == calculate_stockout_risk(inputs())


def test_a_missing_forecast_uses_observed_velocity() -> None:
    observed = calculate_stockout_risk(inputs(sales_velocity_units_per_hour=Decimal("4")))
    absent = calculate_stockout_risk(
        inputs(sales_velocity_units_per_hour=Decimal("4"), forecast_units_per_hour=None)
    )

    assert absent == observed


def test_a_higher_forecast_raises_the_rate_and_a_lower_one_does_not() -> None:
    base = calculate_stockout_risk(inputs(shelf_quantity=8, backroom_quantity=0))
    raised = calculate_stockout_risk(
        inputs(
            shelf_quantity=8,
            backroom_quantity=0,
            forecast_units_per_hour=Decimal("18.25"),
        )
    )
    lower = calculate_stockout_risk(
        inputs(shelf_quantity=8, backroom_quantity=0, forecast_units_per_hour=Decimal("0.5"))
    )

    assert base.level == "normal"
    assert base.demand_units_per_hour == "2"
    assert raised.demand_units_per_hour == "18.25"
    assert raised.level == "near_stockout"
    assert raised.high_demand is True
    assert raised.forecast_units_per_hour == "18.25"
    assert lower.demand_units_per_hour == base.demand_units_per_hour
    assert lower.level == base.level
    assert lower.units_needed == base.units_needed
    assert lower.forecast_units_per_hour == "0.5"


def test_zero_demand_does_not_call_an_empty_shelf_a_stockout() -> None:
    risk = calculate_stockout_risk(
        inputs(shelf_quantity=0, backroom_quantity=0, sales_velocity_units_per_hour=Decimal("0"))
    )

    assert risk.level == "normal"
    assert risk.shelf_hours_of_cover is None
    assert risk.units_needed == "0"
    assert risk.high_demand is False


def test_an_empty_shelf_with_demand_is_a_stockout_even_when_backroom_can_refill() -> None:
    risk = calculate_stockout_risk(
        inputs(shelf_quantity=0, backroom_quantity=54, sales_velocity_units_per_hour=Decimal("4"))
    )

    assert risk.level == "stockout"
    assert risk.shelf_hours_of_cover == "0"
    assert risk.units_needed == "16"
    assert risk.replenishment_units == "16"
    assert risk.uncovered_units == "0"
    assert risk.backroom_covers_horizon is True


def test_bad_inputs_fail_with_a_visible_error() -> None:
    with pytest.raises(StockoutRiskError, match="shelf_quantity"):
        calculate_stockout_risk(inputs(shelf_quantity=-1))
    with pytest.raises(StockoutRiskError, match="shelf_quantity"):
        calculate_stockout_risk(inputs(shelf_quantity=True))
    with pytest.raises(StockoutRiskError, match="sales_velocity"):
        calculate_stockout_risk(inputs(sales_velocity_units_per_hour=Decimal("-1")))
    with pytest.raises(StockoutRiskError, match="horizon_hours"):
        calculate_stockout_risk(inputs(horizon_hours=Decimal("0")))
    with pytest.raises(StockoutRiskError, match="forecast"):
        calculate_stockout_risk(inputs(forecast_units_per_hour=Decimal("-0.1")))
    with pytest.raises(StockoutRiskError, match="observed_at"):
        calculate_stockout_risk(inputs(observed_at=datetime(2026, 10, 10, 8, 0)))
    with pytest.raises(StockoutRiskError, match="sku"):
        calculate_stockout_risk(inputs(sku="  "))


def test_evidence_matches_the_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    evidence = calculate_stockout_risk(
        inputs(shelf_quantity=8, backroom_quantity=54, sales_velocity_units_per_hour=Decimal("18.25"))
    ).as_dict()

    assert schema["additionalProperties"] is False
    assert schema_required(schema) == tuple(evidence)
    assert evidence["assumptions"] == list(ASSUMPTIONS)
    assert set(evidence) == set(schema["properties"])
