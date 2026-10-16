"""Optimizer: deterministic, constrained retail candidate ranker (issue #54).

The ranker expands the Planner's two-to-three candidate set with
deterministically-generated alternatives and ranks them through the
injected KPI evaluator. Numerical decision authority stays with the
DCG-authoritative evaluator and clone scoring; the optimizer never
invokes Gemini, never reads the Live Twin, and never commits to Live
state. Activation is gated by G06 (#53).
"""

from retailtwin_api.agents.optimizer.optimizer import (
    DEFAULT_MAX_CANDIDATES,
    FEASIBLE,
    INFEASIBLE_FACINGS_NONPOSITIVE,
    INFEASIBLE_INVALID_ACTION,
    INFEASIBLE_MIXED_SKU,
    INFEASIBLE_REPLENISH_OVER_BACKROOM,
    INFEASIBLE_SAME_SLOT_MOVE,
    INFEASIBLE_SLOT_OCCUPIED,
    INFEASIBLE_SLOT_UNKNOWN,
    InvalidRankerConfig,
    OptimizerError,
    PLANNER_MIN_CANDIDATES,
    CandidateDraft,
    CandidateRanker,
    RankedCandidate,
    generate_additional_candidates,
    rank_candidates,
    ranked_to_decision,
)

__all__ = [
    "DEFAULT_MAX_CANDIDATES",
    "FEASIBLE",
    "INFEASIBLE_FACINGS_NONPOSITIVE",
    "INFEASIBLE_INVALID_ACTION",
    "INFEASIBLE_MIXED_SKU",
    "INFEASIBLE_REPLENISH_OVER_BACKROOM",
    "INFEASIBLE_SAME_SLOT_MOVE",
    "INFEASIBLE_SLOT_OCCUPIED",
    "INFEASIBLE_SLOT_UNKNOWN",
    "InvalidRankerConfig",
    "OptimizerError",
    "PLANNER_MIN_CANDIDATES",
    "CandidateDraft",
    "CandidateRanker",
    "RankedCandidate",
    "generate_additional_candidates",
    "rank_candidates",
    "ranked_to_decision",
]