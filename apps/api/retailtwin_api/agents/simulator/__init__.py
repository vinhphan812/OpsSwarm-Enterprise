"""Simulator: score normalized decisions on a clone of the live snapshot."""

from retailtwin_api.agents.simulator.branch import (
    CONTEXT_MISMATCH,
    EVALUATION_FAILED,
    FORMULA_ID,
    INVALID_REQUEST,
    INVALID_SNAPSHOT,
    CandidateEvaluator,
    LiveView,
    ScoredCandidate,
    SimulationError,
    SimulationResult,
    SlotView,
    simulate,
)

__all__ = [
    "CONTEXT_MISMATCH",
    "CandidateEvaluator",
    "EVALUATION_FAILED",
    "FORMULA_ID",
    "INVALID_REQUEST",
    "INVALID_SNAPSHOT",
    "LiveView",
    "ScoredCandidate",
    "SimulationError",
    "SimulationResult",
    "SlotView",
    "simulate",
]
