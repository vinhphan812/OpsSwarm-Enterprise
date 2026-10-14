# Simulator

ADR 0013. `simulate` scores normalized `Decision` values on a clone of one `LiveView`.

The injected evaluator is the deterministic KPI service from issue #33. This package does not recompute the formula and does not accept a model response. Each returned decision keeps its actions and reason, and receives the shared `simulation_id` plus that candidate's `business_score`. The live snapshot is unchanged. A context mismatch or an evaluator failure returns no partial result.
