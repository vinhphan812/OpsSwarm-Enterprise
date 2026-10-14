# 0013. Score candidate plans on a simulation clone

Date: 2026-10-13

## Status

Accepted

## Context

Issue #15 needs each planner decision applied somewhere other than the Live Twin, with a measurable result. ADR 0012 already emits two or three `Decision` values whose `kpi_score` is the unscored sentinel `-1.0`. Issue #33 already scores a snapshot clone with formula `simulation-kpi-v1`. The owner comment on #15 says the simulation step consumes that evaluator and does not rebuild it, and that the input is a normalized `Decision`, not an OpenAI or Gemini response.

Scoring inside the planner was set aside. ADR 0012 keeps the model away from KPI numbers. Writing the clone back to the live snapshot was set aside. Only the Executor may change the Live Twin, and only after the Decision Context Guard. Returning a partial list when one candidate fails was set aside. A caller could then treat a missing candidate as if it had been scored.

## Decision

The simulator in `apps/api/retailtwin_api/agents/simulator/branch.py` accepts normalized `Decision` values, one `LiveView`, and an injected evaluator. Every decision must use that live `context_version`, `store_id`, and `correlation_id`. The simulation id is `sim-` plus the correlation id. The module sends each decision's actions and a copy of the snapshot to the evaluator. It does not apply the actions itself.

The evaluator must return formula `simulation-kpi-v1` for that same simulation id, candidate id, and correlation id. The returned decision copies the action list and the reason, sets `simulation_id`, and sets `expected_impact.kpi_score` from the evaluator's `business_score` string. The full evaluator mapping is kept beside the frozen `SimulationKPIResult`. The original decision and the `LiveView` stay as the caller passed them.

An invalid snapshot, a context mismatch, or any evaluator failure rejects the whole call. No scored candidate is returned from that call. The simulator does not import a model SDK and does not import the simulation package. Tests bind the real `evaluate_candidate` function.

## Consequences

A planner decision can be compared by the deterministic score without changing the live shelf. Issue #16 can read `simulation_id` and the score. It still has to enforce the guard. Readers must use the returned decision for the score. The input decision remains unscored.

The 3D simulation view stays issue #92. A live Vertex call remains issue #2. This record does not change the KPI formula, the planner, the Decision Context Guard, or No-Stale-Commit.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/161
- Issue: #15
- Supersedes:
- Superseded by:
