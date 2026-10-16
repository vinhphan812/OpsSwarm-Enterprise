# Optimizer (issue #54)

Deterministic, constraint-aware retail candidate ranker. The optimizer
expands the Planner's two-to-three candidate set with deterministically-
generated alternatives and ranks them through the injected KPI evaluator.

Numerical decision authority stays with the DCG-authoritative evaluator
and clone scoring:

- the optimizer never invokes Gemini, OpenAI, or Vertex;
- the optimizer never reads the Live Twin;
- the optimizer never commits to Live state;
- the optimizer never recomputes the simulation KPI formula.

Activation is gated by G06 (#53). The simulator accepts an optional
`CandidateRanker`; when it is `None` the Planner's two-to-three
candidates flow through unchanged. Two algorithms are shipped:

- `heuristic_v1` — generate variants, score each with the KPI
  evaluator, sort by score descending;
- `lp_v1` — a linear-programming relaxation proxy (`sales_velocity *
  price` weighted by post-action shelf quantity) that pre-ranks the
  pool before the KPI evaluator runs.

Public surface (see `optimizer.py`):

- `CandidateRanker(algorithm, max_candidates)` — configuration.
- `CandidateDraft` — an unsorted candidate.
- `RankedCandidate` — a scored, feasible, ranked candidate.
- `generate_additional_candidates(snapshot, *, intent)` — deterministic
  optimizer drafts derived from the current snapshot.
- `rank_candidates(plan, live_snapshot, *, kpi_evaluator, ranker,
  intent, simulation_id)` — full ranking pipeline.
- `ranked_to_decision(ranked, *, base, agent_id)` — wrap a
  `RankedCandidate` as a `Decision` so the existing simulator can
  score it.

The optimizer respects:

- shelf capacity (`facings >= 1`);
- backroom quantity (`replenish.quantity <= backroom_quantity`);
- slot uniqueness (a `move_product` cannot land on an occupied slot).

`feasibility` on every `RankedCandidate` reports the post-action
backroom quantity, facings, and slot id so the operator can see why
each draft was rejected, when it was rejected.