"""Deterministic stockout-risk evidence."""

from risk.stockout import (
    ASSUMPTIONS,
    DEFAULT_HORIZON_HOURS,
    FORMULA_ID,
    HIGH_DEMAND_UNITS_PER_HOUR,
    StockoutInputs,
    StockoutRisk,
    StockoutRiskError,
    calculate_stockout_risk,
)

__all__ = [
    "ASSUMPTIONS",
    "DEFAULT_HORIZON_HOURS",
    "FORMULA_ID",
    "HIGH_DEMAND_UNITS_PER_HOUR",
    "StockoutInputs",
    "StockoutRisk",
    "StockoutRiskError",
    "calculate_stockout_risk",
]
