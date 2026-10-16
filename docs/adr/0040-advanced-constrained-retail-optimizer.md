# 0040. Advanced constrained retail optimizer

Date: 2026-10-16

## Status

Proposed

## Context

Issue #54 introduces a deterministic, constraint-aware optimizer that
expands the Planner's two-to-three candidate set before the simulator
scores it on a clone. The Planner already binds `context_version`,
`context_timestamp`, and the evidence bundle for each candidate
(ADR 0012); the simulator already scores every decision on a clone of
one `LiveView` and never touches the Live Twin (ADR 0013).

The current path is bound to the Planner's output. The Planner calls
Gemini through the provider-neutral runtime (ADR 0008) to ask for two
or three structured candidates; the simulator then scores them with
`simulation-kpi-v1` (issue #33). The Planner can only return the
candidates it sees, so the simulator cannot search beyond them. A
retail operator may want to compare more replenishment quantities,
more facing options, and more slot moves than the model proposes.

ADR 0014 (the Decision Context Guard) keeps numerical decision
authority in the deterministic stack. The optimizer must keep the same
shape: it stays inside the API, it never invokes Gemini, OpenAI, or
Vertex, it never reads the Live Twin, it never commits to Live state,
and the existing KPI formula remains the only score on the page. The
ranker is an expansion and re-ordering pass, not a new decision-maker.

The implementation can land before G06 (#53) passes. Activation is
gated on G06 evidence: the simulator accepts an optional
`CandidateRanker`; when it is `None` the Planner's two-to-three
candidates flow through unchanged. Once G06 records reproducible
flagship evidence, the ranker can be turned on without a code change.

## Decision

Add a new agent package `apps/api/retailtwin_api/agents/optimizer/`:

- `CandidateRanker` is a frozen dataclass with two fields:
  `algorithm` (`"heuristic_v1"` or `"lp_v1"`) and `max_candidates`
  (default `8`, integer, minimum `2`).
- `CandidateDraft` — an unsorted candidate (`source`, `sku`,
  `slot_id`, `actions`, `rationale`, `provenance`).
- `RankedCandidate` — `CandidateDraft` plus the ranker-computed
  `score`, a `feasibility` dict, and the `rank` (1-based).
- `generate_additional_candidates(snapshot, *, intent)` produces
  deterministic optimizer drafts for every SKU in the snapshot.
  Determinism comes from the tuple-ordered iteration over
  `snapshot.slots` plus sorted sub-iteration; the same inputs always
  yield the same ids.
- `rank_candidates(plan, live_snapshot, *, kpi_evaluator, ranker,
  intent, simulation_id)` combines the Planner's plan with the
  optimizer's drafts, filters to the focal SKU, runs the feasibility
  check, scores each feasible candidate through the injected
  `kpi_evaluator`, and returns the top-`max_candidates` in score
  order with feasible entries before infeasible ones.
- `ranked_to_decision(ranked, *, base, agent_id)` wraps a
  `RankedCandidate` as a `Decision` for the simulator, reusing the
  base decision's `context_version`, `context_timestamp`, and
  `evidence`.

Two algorithms are shipped:

- `heuristic_v1` — generate variants, score each with the KPI
  evaluator, sort by `score` descending. Stable tie-break by
  `candidate_id`.
- `lp_v1` — a linear-programming relaxation proxy that pre-ranks
  candidates by `sales_velocity * price` (per slot) plus the action
  type order (`replenish_shelf`, `change_facings`, `move_product`)
  before the KPI evaluator runs. The final order is still the
  evaluator's score.

Wire `apps/api/retailtwin_api/agents/simulator/branch.py`:

- `simulate(decisions, live, *, evaluate, ranker=None,
  ranker_intent=None)` now accepts an optional `ranker`. When the
  ranker is `None`, the existing flow runs. When it is provided,
  `_ranked_decisions` calls `rank_candidates` against the same
  `evaluate` callback, converts each `RankedCandidate` to a `Decision`,
  and the simulator's existing scoring loop continues. The KPI
  formula is unchanged; the simulator still applies `simulation-kpi-v1`
  to every ranked candidate.
- Any optimizer-side exception (`OptimizerError`,
  `InvalidRankerConfig`, or an unexpected exception) surfaces as
  `SimulationError(reason=EVALUATION_FAILED)`, matching the existing
  contract.

The optimizer must respect shelf capacity (`facings >= 1`), backroom
quantity (`replenish.quantity <= backroom_quantity`), and slot
uniqueness (`move_product.to_slot` must be unoccupied). These are
encoded in the per-draft `feasibility` map:

```
{
  "feasible": bool,
  "reasons": [...],
  "backroom_after": int | None,
  "facings_after": int | None,
  "slot_after": str | None,
}
```

Infeasible drafts receive a sentinel score (`-inf`) and never reach
the KPI evaluator, so a bad draft cannot fail the whole simulation.
The simulator still receives only the feasible top-`max_candidates`
and applies the existing scoring loop.

The optimizer is deterministic: the same plan, snapshot, evaluator,
and ranker configuration produce the same ids, the same score order,
and the same feasibility map. Activation is gated by G06 (#53); a
`None` ranker is the default and keeps the existing behaviour.

## Consequences

A flagship run can compare more candidates without changing the
Planner, the Simulator, the Decision Context Guard, or the KPI
formula. The optimizer never invents a score: the ranker delegates
scoring to the existing `kpi_evaluator`. The DCG-authoritative
`simulation-kpi-v1` formula is the only number on the page.

Operators can keep the Planner's two-to-three candidates unchanged
and only turn on the optimizer once G06 (#53) records reproducible
flagship evidence. Activation is a one-line configuration change at
the ranker injection site.

The optimizer imports `agents.simulator.branch` for the type
contracts (`CandidateEvaluator`, `LiveView`, `SlotView`) but not the
scoring chain itself; it does not import `kpi.evaluator` or any model
SDK. The lazy import inside `_ranked_decisions` keeps the simulator
package's import graph unchanged when no ranker is configured.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/54
- Issue: #54
- Supersedes:
- Superseded by: