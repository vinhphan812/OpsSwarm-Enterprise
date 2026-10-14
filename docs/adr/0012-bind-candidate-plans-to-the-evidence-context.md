# 0012. Bind candidate plans to the evidence context

Date: 2026-10-13

## Status

Accepted

## Context

Issue #14 needs two or three candidate plans that simulation can run. Free-form model prose is not a decision. ADR 0008 already supplies provider-neutral structured output. ADR 0011 supplies one versioned `EvidenceBundle`. The frozen `Decision` carries `context_version`, `context_timestamp`, `evidence`, `proposed_actions`, and `expected_impact`. The MVP actions are only `move_product`, `change_facings`, and `replenish_shelf`.

Letting the model write the context version or the evidence was set aside. A later context change would be invisible, and No-Stale-Commit depends on the version the planner actually used. Letting the model write `kpi_score` was set aside. The project rule is that the simulator computes KPI numbers and the model only explains them. Parsing a forbidden action out of prose and keeping the other candidates was set aside. The owner comment on #14 says invalid structured output fails explicitly, with no provider-specific best-effort parse. Running simulation inside the planner was set aside. That integration is issue #15.

## Decision

The planner in `apps/api/retailtwin_api/agents/planner/plans.py` accepts one `EvidenceBundle`, an injected `LlmProvider`, a context version, and a context timestamp. It calls the provider with an empty tool list and the structured schema for two or three candidates. Each candidate has a short reason and one to three actions. The schema is the three MVP action models. `response.content` is validated against that schema and then parsed by those models. Tool calls on the response are not executed.

The planner copies the evidence bundle onto each `Decision`. It sets `context_version` and `context_timestamp` from the arguments, not from the model. `simulation_id` is null. `expected_impact.description` is the stripped reason. `expected_impact.kpi_score` is `-1.0` (`UNSCORED_IMPACT`). That sentinel means simulation has not scored the candidate. It is not a business score. Issue #15 replaces it with the deterministic KPI.

An action is forbidden when its SKU is not the observed SKU, a move does not start at the observed slot, a move starts and ends on the same slot, or a replenishment asks for more units than the observed backroom. Any forbidden action, any schema failure, or any provider failure rejects the whole plan. Nothing from that call is returned for simulation. An insufficient bundle is rejected before the provider is called.

The planner does not write the Live Twin and does not import a model SDK.

## Consequences

Simulation receives only schema-valid decisions tied to one evidence bundle and one context version. A forbidden action never arrives as a candidate. Readers must not treat `-1.0` as a measured KPI. Issue #15 scores these decisions in an isolated simulation and does not ask the model for a replacement number.

A live Vertex call remains issue #2. This record does not change the investigator, the observer, the tool registry, the Decision Context Guard, No-Stale-Commit, or the analytics lander.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/155
- Issue: #14
- Supersedes:
- Superseded by:
