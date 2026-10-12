# RetailTwin AI — Current Project Status

**Status date:** 2026-10-08
**Purpose:** separate what is implemented now from the target architecture described elsewhere.

## Current baseline on main

The repository contains two merged day-0 slices: a view-only 3D web scaffold from PR #56 / issue #3, and a fixture-backed FastAPI plus frontend API integration from PR #57 / issue #8.

Implemented on `main`:
- Vite + React 18 + TypeScript;
- React Three Fiber 8 / Three.js scene;
- store fixture `store-001`;
- shelves `A01`, `A02`, `B01`, `B02`;
- products `P001` and `P002`;
- stable scene entity IDs via `name` and `userData.entityId`;
- responsive camera framing;
- orbit-only interaction;
- scene tests;
- Agent Activity panel with `StoreStatus`;
- `apps/api` routes `GET /health`, `GET /store`, `GET /inventory/{sku}`, and `POST /events`;
- typed web client for health, store, and inventory;
- reads from the committed fixture `data/schemas/store-state.example.json`;
- in-memory event intake: one `event_id` names one immutable normalized payload, an identical payload returns HTTP 200, and a different payload returns HTTP 409 `event_id_conflict`;
- `POST /events` does not change inventory, does not write Live Twin state, and does not publish;
- store-events backbone: pull subscription `store-events-analytics` on topic `store-events`, and BigQuery tables `retailtwin.sales_events`, `retailtwin.inventory_events`, and `retailtwin.agent_actions`;
- Weekend Demand Surge fixture for P017 (issue #30). Seed 1 rebuilds thirteen `sale.completed` events, Friday 50 units and Saturday 73 units in matching four-hour windows, increase 0.46. `python -m retailtwin_api.demand_surge publish` sends them on `store-events`. A replay keeps one row per event id. This does not start the Observer and does not change the Live Twin;
- deterministic demand forecast for issue #31 in `services/forecasting/demand`. The next horizon repeats the latest window of sales. The P017 weekend series forecasts 73 units, 18.25 per hour, direction up from Friday's 50. BigQuery ML is not called. A disabled or unavailable model keeps this fallback. This does not read or change the Live Twin;
- deterministic stockout risk for issue #32 in `services/forecasting/risk`. Shelf quantity, observed units per hour, and backroom quantity produce evidence over a 4-hour horizon. A forecast can only raise the rate. The calculator does not read the Live Twin and does not call a forecasting service;
- deterministic `sale.completed` publisher. The lander claims each `event_id` in Firestore `store_event_claims`. The landing lease chooses who may submit the derived insert, and that insert uses one BigQuery job id for the claim generation, so a takeover joins the same job. A replay of the same payload is a duplicate. A different payload is a conflict and does not replace the claim or the row. `correlation_id` is kept on the message and the row. A rejected message is quarantined before it is acknowledged;
- ADR 0001, 0002, 0003, 0004, 0005, 0006, and 0007;
- tracked `apps/web/package-lock.json`.

The 3D scene and the API are **not Firestore Live Twin**. Issue #4, on `main` through PR #65, reads `GET /store` and places products on the static layout (ADR 0007). Issue #6 replaces `open_store` with Firestore and keeps the four routes. `store_event_claims` is an idempotency ledger for this backbone, not that Live Twin. `infrastructure/gcp/verify-store-events.sh` checks the subscription and the three tables. The smoke command publishes `data/synthetic/sale-completed.json` and checks that a replay stays one row.

## Google Cloud foundation

Issue #5 applies the shared project `retailtwin-ai-511002` in `us-central1`. The shape is the always-free layout in [infrastructure/gcp/README.md](../infrastructure/gcp/README.md) and [ADR 0004](adr/0004-keep-the-cloud-foundation-on-free-tier.md): required APIs on, Compute Engine and the other large services off, two service identities and no keys. Firestore `(default)` is Standard edition Native mode. Issue #6 still seeds the Live Twin. `store_event_claims` is an idempotency ledger for this backbone, not that Live Twin. This backbone adds subscription `store-events-analytics` and the three BigQuery tables. There is no Cloud Run service and no Gemini call.

The monthly budget `retailtwin-dev-guard` is 25,000 VND, about 1 USD, on this project only, with alerts at 50%, 90%, and 100%. The billing account currency is VND. The alert does not disable billing.

## Work in progress

Issue #4 is on `main` through PR #65.
- The scene reads `GET /store` from `apps/api` and places products on the static layout (ADR 0007). P001 is bound by its SKU.
- The scene polls `GET /store` every 5 s. When reads fail, it backs off up to 60 s. It keeps the last state, or empty shelves, on screen when the API is down.
- The web app only reads the API. It does not call `POST /events`.
- Tests cover the HTTP path from the committed seed to the scene: a P001 change in the seed redraws P001, and a reload rebuilds the same state.
- Still open: a manual run against a live `apps/api`. Firestore stays with #6, so today the state comes from the JSON seed.

Issue #58 is closed. The web build and test workflow is on `main`.

Issue #60 is closed (PR #68). Coverage instrumentation is in place and running in CI.
Behavior tests exist. There is no hard coverage gate yet, so a passing test count is not
a coverage percentage. Coverage is measured; threshold enforcement is phase 2 before
Foundation Gate #10.

Baseline (PR #68):
- API: 89% line, 85% branch (pytest-cov, 269 stmts, 44 branches)
- Web: 91% stmt/line, 91% branch (Vitest v8, 12 tests)

## Not implemented yet

Do not infer implementation merely because a component is documented in the target architecture. The following remain planned/open unless their issue is explicitly completed:

- Firestore-backed Live Twin and seed/reset;
- Observer activation from a store event;
- later analytical tables such as product performance and simulation results;
- Gemini on Vertex AI real tool call;
- constrained Agent Tool Registry;
- Observer, Investigator and structured Planner;
- Simulation Twin and KPI evaluator;
- deterministic Decision Context Guard implementation;
- No-Stale-Commit enforcement;
- commit authorization/token and guarded Executor;
- post-action Verifier and automatic re-plan;
- 3D binding to Live/Simulation Twin state;
- Cloud Run production deployment;
- end-to-end autonomous scenario;
- submission gates G02–G06.

## Current release-gate status

| Gate | Status | Evidence required |
| --- | --- | --- |
| Day-0 / Foundation #10 | NOT PASSED | integrated web + API + Firestore + Pub/Sub + Gemini tool + Cloud Run smoke test |
| G02 Twin Control #49 | NOT PASSED | agent tool changes Simulation Twin + 3D while Live remains unchanged |
| G03 Autonomous #50 | NOT PASSED | store event starts agent without prompt |
| G04 Guard #51 | NOT PASSED | stale decision is rejected and cannot mutate Live Twin |
| G05 Live Commit #52 | NOT PASSED | valid guarded decision changes Live Twin and 3D |
| G06 Submission #53 | NOT PASSED | 20 consecutive flagship E2E runs |

Gate status changes only when the corresponding issue contains reproducible evidence and is closed intentionally.

## Immediate critical path

1. Issue #58 is closed. The web build and test workflow is on `main`. Issue #60 adds the coverage baseline and threshold to that gate.
2. Complete Firestore (#6), the Gemini real read tool (#2), and Cloud Run (#9). The store-events backbone (#7) claims each `sale.completed` event id once. The landing lease chooses who may submit the derived insert, and that insert uses one BigQuery job id for the claim generation. A replayed event id is a duplicate. It does not start the Observer. Issue #6 still owns the Live Twin.
3. Pass Foundation Gate #10. #10 stays open: Firestore, Gemini real tool use, and Cloud Run are still required. A store event does not yet start an investigation.
4. Continue the autonomous path: Tool Registry → Observer → Investigator → Planner → Simulation → DCG → Executor → Verifier.
5. Bind those state changes to the 3D Live/Simulation views.
6. Pass G02 → G03 → G04 → G05 → G06 in order.

## Documentation rule

Use these terms consistently:

- **Implemented/current** means code exists on `main` and has appropriate verification.
- **In progress** means an open PR exists but is not yet part of `main`.
- **Target/planned** means architecture or issue scope only.
- **Gate passed** means the gate issue has reproducible evidence and is closed.

Narrative architecture documents describe the target product. This file describes the repository's current maturity and must be updated whenever a release gate changes or a major subsystem lands.
