"""Deterministic KPI scores for simulation candidates."""

from kpi.evaluator import (
    ASSUMPTIONS,
    FORMULA_ID,
    ChangeFacings,
    KpiError,
    KpiLedger,
    KpiResult,
    MoveProduct,
    ReplenishShelf,
    SimulationSnapshot,
    SlotState,
    evaluate_candidate,
)

__all__ = [
    "ASSUMPTIONS",
    "FORMULA_ID",
    "ChangeFacings",
    "KpiError",
    "KpiLedger",
    "KpiResult",
    "MoveProduct",
    "ReplenishShelf",
    "SimulationSnapshot",
    "SlotState",
    "evaluate_candidate",
]
