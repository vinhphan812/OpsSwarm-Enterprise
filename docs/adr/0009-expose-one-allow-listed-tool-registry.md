# 0009. Expose one allow-listed tool registry

Date: 2026-10-13

## Status

Accepted

## Context

Issue #11 needs a typed tool boundary before the Observer, Investigator, or Planner can run. ADR 0008 already gives the agent one provider-neutral `LlmTool` list, and the OpenAI-compatible and Vertex adapters translate that list. The frozen contracts name three capabilities: `READ`, `SIMULATION`, and `COMMIT_REQUEST`. The domain model names the MVP read tools, the three live-shaped actions, and `submit_action_for_commit`. It also says Gemini does not call a generic live update. Only the guarded Executor may change the Live Twin, and that executor is still a later issue.

Two provider-specific tool lists were set aside. They would drift, and ADR 0008 already forbids that split inside agent code. A fourth `LIVE_WRITE` capability was set aside. It would give the model a path around the Decision Context Guard. Computing forecasts, stockout risk, or KPI scores inside the registry was set aside too. Those numbers already belong to the deterministic services, and a tool that invents one would break the rule that the model only explains returned evidence.

## Decision

The orchestrator exposes one allow-listed registry at `apps/api/retailtwin_api/agents/orchestrator/tool_registry.py`. Each tool is one pydantic model. The registry derives one JSON object schema from that model and hands it to the adapters as `LlmTool`. Agent code does not keep a second OpenAI or Gemini definition.

A call is accepted only when the tool is registered, the arguments match that model, and the caller granted that tool's capability. An unknown name is `unknown_tool`. A known live-write name, in any letter case, is `live_write_forbidden`. A missing or extra argument is `invalid_arguments`. A capability that was not granted is `permission_denied`. A handler that exceeds its timeout is `timeout`. The registry does not issue a commit authorization.

The store registry offers `get_store_state`, `get_shelf_state`, `get_inventory`, `get_backroom_inventory`, `move_product`, `change_facings`, `replenish_shelf`, `create_simulation`, and `submit_action_for_commit`. The read tools return the store view they were given. The simulation tools record a validated action or a new simulation id. `submit_action_for_commit` records the decision id and action count. None of these handlers mutate the store.

The other MVP catalog names, including `forecast_demand`, `get_stockout_risk`, `compare_scenarios`, and `calculate_business_impact`, stay out of the model allow-list until a caller binds a deterministic port. The registry returns that port's value unchanged.

A live Vertex call that uses this registry remains issue #2. This record does not authorize that call, and it does not replace the Decision Context Guard, the Executor, or the simulation service.

## Consequences

A new tool is a catalog entry plus a handler that does not mutate the Live Twin. The same `LlmTool` list is what both adapters send. Issue #2 must use this list. Later investigation uses the `READ` grant, simulation uses the `SIMULATION` grant, and a commit request uses `COMMIT_REQUEST`.

Analytical tools stay dark until their deterministic source is bound, so the model is not offered a tool that would have to invent a KPI. The activity log is process memory. It is not the Live Twin and it is not an authorization. A programmer can still register a badly behaved handler under a new name; review has to refuse that handler, and the live-write names cannot be registered at all.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/119
- Issue: #11
- Supersedes:
- Superseded by:
