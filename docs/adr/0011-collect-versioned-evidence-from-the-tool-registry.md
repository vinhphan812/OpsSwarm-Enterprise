# 0011. Collect versioned evidence from the tool registry

Date: 2026-10-13

## Status

Accepted

## Context

Issue #13 needs a reproducible `EvidenceBundle` for one investigation: what was observed, when, and from which entity version. ADR 0008 supplies the provider-neutral `LlmProvider`. ADR 0009 supplies the allow-listed tool registry and keeps analytical tools unbound until a deterministic port is attached. ADR 0010 hands the investigator an `InvestigationStart` that carries the `StoreEvent` and an investigation id, and no prompt.

The frozen `EvidenceItem` has `event_type` and `payload`. The domain note shows a richer item (`entity_id`, `version`, `observed_at`, `value`). Replacing the frozen model was set aside. Letting the model write quantities into the bundle was set aside, including when a mandatory source is missing. Importing `services.forecasting` from the API package was set aside: the API test path does not include that package, and the forecast formula already lives in the deterministic service. Calling every mandatory tool whenever the model omits one was set aside. Omission is a missing source, not permission to fetch a substitute. Making stockout risk mandatory was set aside. That figure is a later calculation and must not be invented from inventory.

## Decision

The investigator in `apps/api/retailtwin_api/agents/investigator/evidence.py` accepts an `InvestigationStart`, an injected `LlmProvider`, an injected `ToolRegistry`, and the collection clock. It asks the provider to call read tools for that sale. It executes only the tool calls the provider returns, and only with the `READ` grant. `response.content` is not evidence and is not logged.

The mandatory sources are inventory (`get_inventory`), shelf (`get_shelf_state`), recent sales (`get_sales_history`), forecast (`forecast_demand`), promotions (`get_promotions`), and planogram (`get_planogram`). A successful observation is an `EvidenceItem` whose payload holds `source`, `entity_id`, `version`, `observed_at`, and `value`. The value is the tool output. The version is the tool's `version`, or for a shelf the version of the investigation SKU on that shelf. A result with no version, a result for a different SKU, or a tool error is not kept as a quantity. The bundle records `insufficient_evidence` with the source and the error code. `is_sufficient` is true only when every mandatory source has a versioned result. `entity_versions` records the investigation SKU only when inventory itself returned a version.

`get_promotions` is a catalog `READ` tool. It stays off the default exposed list until a caller binds it. `bind_read_port` turns a `None`, a missing version, or an exception into `source_unavailable` without copying the exception text. Forecast numbers come from that injected port. The investigator does not compute them. The same `EvidenceBundle` shape is returned for every provider. A provider failure raises `InvestigatorError` and does not return a guessed bundle.

The investigator does not write the Live Twin, does not grant `SIMULATION` or `COMMIT_REQUEST`, and does not import a model SDK.

## Consequences

A planner can tell an observed fact from a missing mandatory source. An empty promotion list returned by a bound port is an observation. A missing port is `insufficient_evidence`. Removing one mandatory binding cannot be filled in from inventory or from model prose.

The forecast service stays outside the API package. A test or a later adapter binds `forecast_demand` to the deterministic formula. Stockout risk can be bound later and is not required for a sufficient bundle. A live Vertex call remains issue #2. This record does not change the analytics lander, the demand-surge publisher, or the observer ack rule.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/121
- Issue: #13
- Supersedes:
- Superseded by:
