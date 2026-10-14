# Planner

ADR 0012. `plan` turns one sufficient `EvidenceBundle` into two or three `Decision` values.

The injected provider must return structured candidates. The planner validates each action against `move_product`, `change_facings`, and `replenish_shelf`, and against the observed SKU, slot, and backroom quantity. A forbidden action fails the plan before simulation. The planner then binds `context_version`, `context_timestamp`, and the evidence bundle. The stored reason is the candidate summary only.

The model cannot set the context, the evidence, the simulation id, or a KPI score. `expected_impact.kpi_score` is `UNSCORED_IMPACT` (`-1.0`) until simulation scores the candidate. That value is not a business score. The planner does not import a model SDK and does not write the Live Twin.
