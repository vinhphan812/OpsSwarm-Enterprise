# RetailTwin AI — Current Project Status

**Status date:** 2026-10-15
**Purpose:** separate what is implemented now from the target architecture described elsewhere.

## Current baseline on main

The repository contains three merged slices: a view-only 3D web scaffold from PR #56 / issue #3, a fixture-backed FastAPI plus frontend API integration from PR #57 / issue #8, and a Firestore Live Twin boundary from PR #106 / issue #6.

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
- simulation KPI evaluator for issue #33 in `services/simulation`. A candidate's actions are applied to a clone, then stockout risk, service level, movement cost, and a business score are stored for that `simulation_id`. The same actions repeat the stored result. This does not read or change the Live Twin and does not run the agent;
- allow-listed tool registry for issue #11 (ADR 0009) in `apps/api/retailtwin_api/agents/orchestrator/tool_registry.py`. One pydantic model becomes one `LlmTool`, and the existing OpenAI-compatible and Vertex adapters translate that list. The store registry serves `get_inventory`, `get_store_state`, `get_shelf_state`, and `get_backroom_inventory` from the store it is given. `move_product`, `change_facings`, `replenish_shelf`, and `create_simulation` record a simulation request. `submit_action_for_commit` records a commit request and does not authorize it. None of these handlers change the store. A live-write name is refused. `forecast_demand` and the other analytical catalog tools stay off the model list until a deterministic port is bound. This registry does not call Gemini. The live read is issue #2 (ADR 0021);
- observer for issue #12 (ADR 0010) in `apps/api/retailtwin_api/agents/observer/consumer.py`. A new `sale.completed` starts one investigation through an injected `start_investigation` call. The handoff carries the `StoreEvent` and `inv-` plus `event_id`, and it has no prompt. The same payload is a duplicate. A different payload is a conflict and does not replace the first event. The message is acknowledged after that record is committed. The analytics lander is unchanged and still does not start an investigation. This ledger is process memory. It does not write the Live Twin and it does not call a model. The demand-surge publisher still only publishes;
- planner for issue #14 (ADR 0012) in `apps/api/retailtwin_api/agents/planner/plans.py`. A sufficient `EvidenceBundle` is planned by asking the injected provider for two or three structured candidates and validating those actions against the observed SKU, slot, and backroom. The planner binds `context_version`, `context_timestamp`, and the evidence. The stored text is the reason summary. A forbidden action rejects the plan before simulation. `expected_impact.kpi_score` stays `-1.0` until simulation scores the candidate. This does not write the Live Twin and does not import a model SDK;
- Decision Context Guard for issue #16 (ADR 0014) in `apps/api/retailtwin_api/guard/decision_context_guard/`. Six gates run in order and the first failure decides: integrity and evidence sufficiency (`DENY`), the live version of each SKU an action touches (`REFRESH_REQUIRED`, or `DENY` when the evidence has no version), freshness within `RETAILTWIN_DCG_FRESHNESS_SECONDS`, default 120 (`REFRESH_REQUIRED`), shelf, backroom and slot feasibility (`DENY`), and the autonomous policy (`HUMAN_REVIEW` past the action or replenishment limit, `DENY` for an action type outside the allow-list). A Live Twin read failure is `DENY`. The result carries a context hash over the decision id, the live versions read and the actions. The guard reads the Live Twin, never writes it, and imports no model SDK. No-Stale-Commit for issue #17 (ADR 0015) wraps it: `NoStaleCommit.authorize` re-reads the Live Twin and returns a `CommitBinding` of the touched SKU versions only on `ALLOW`, and `recheck` runs the guard again immediately before a commit, so a decision built at version N is `REFRESH_REQUIRED` once a touched SKU is at N+1 and an altered action list is `DENY BINDING_MISMATCH`. Each check records a `GuardAuditEvent` with the correlation id in process memory. The guarded Executor for issue #18 (ADR 0016) is the only Live Twin writer: `POST /simulations/{id}/approve` reads a Decision from an injected `DecisionSource`, runs `NoStaleCommit.authorize`, issues an HMAC-signed single-use authorization bound to the decision id, context hash, per-action hashes, live versions and a 30s expiry, and the Executor redeems it, rechecks the guard, and writes every touched SKU and the store version step in one atomic commit, each document conditional on the version it read (Firestore `updateTime` precondition, ADC auth). A missing, tampered, expired, reused or action-mismatched token changes nothing. `GET /store` reads an in-process Live Twin seeded from the fixture (`LIVE_TWIN_BACKEND=memory`), so a commit shows on the next read. The Planner does not persist Decisions, so production returns `503 decisions_unavailable` until a source is injected. This does not score candidates; simulation stays issue #15;
- post-action Verifier for issue #19 (ADR 0017) in `apps/api/retailtwin_api/agents/verifier/verify.py`. `verify` re-reads each SKU a decision's actions touch and compares that live row with the transition the actions imply from the pre-commit snapshot: replenish moves quantity from backroom to shelf, facings replace the facing count, and a move changes only `slot_id`. Each touched SKU must be one version ahead. The result is `VERIFIED`, `REGRESSION`, or `INCONCLUSIVE`. `expected_impact.kpi_score` of `-1.0` is the planner's unscored sentinel and is not compared. Any other expected score is compared only with a decimal the caller supplies. This does not recompute the #33 formula, does not write the Live Twin, and does not import a model SDK. A process-memory audit event stores the correlation id. No route calls it;
- automatic re-plan for issue #20 (ADR 0018) in `apps/api/retailtwin_api/agents/orchestrator/replan.py`. `replan` authorizes the current decision with `NoStaleCommit`. `ALLOW` is rechecked, and only then is that decision and its binding passed to an injected commit port. `DENY` tries the next candidate from the same refresh. `HUMAN_REVIEW` stops. `REFRESH_REQUIRED` discards the binding and calls the injected provider through `investigate` and `plan`, keeping the same correlation id and store id. The context version on the new decision comes from an injected source read after that refresh. It is not copied from the rejected decision, and a later refresh reads the source again. `RETAILTWIN_REPLAN_MAX_REFRESHES` defaults to 1 and counts those refresh cycles only. A provider, planner, simulation, or commit failure stops without another refresh and without another commit. An injected simulation port may score the new decisions; without one, `simulation_id` stays empty and `kpi_score` stays `-1.0`. This module does not write the Live Twin, does not import the simulator, and does not branch on a provider name. No route calls it;
- bounded automatic rollback for issue #55 (ADR 0039) in `apps/api/retailtwin_api/agents/executor/recovery.py`. `propose_recovery` generates an inverse action for a `REGRESSION` or `INCONCLUSIVE` verifier verdict (`replenish_shelf` → `deplete_shelf`, `change_facings` → restore baseline, `move_product` → swap slots back) and `execute_recovery` re-runs the Decision Context Guard on fresh reads, refuses on `stale_recovery` or guard `DENY`, and applies the inverse through the same atomic-commit boundary the guarded Executor uses. The audit chain shares the original `correlation_id` and `decision_id`. `RecoveryPolicy(max_attempts=1, inverse_only=True, linkage_required=True)` caps the loop. `RECOVERY_AUTO_ENABLED` (default `False`) gates the policy at the wired Executor entry-point until G06 submission-gate evidence is on record;
- provider registry for issue #136 (ADR 0020) in `apps/api/retailtwin_api/llm/factory.py`. `create_provider` looks up a registered builder. The shipped names are `fake`, `openai_compatible`, and `vertex_gemini`. Another adapter is a registration, not an edit to the planner or the investigator. In production the call accepts only `vertex_gemini` on `retailtwin-ai-511002` in `us-central1` and refuses a fake provider, a loopback endpoint, and an API key. That name cannot be replaced or removed, and the call uses the shipped Vertex builder. A failed builder is not replaced with the fake provider. The day-0 API does not construct a provider. The live proof is the inventory read (ADR 0021);
- agent-action audit for issue #35 (ADR 0019) in `apps/api/retailtwin_api/audit/trail.py`. `record_trace` appends one row per stage (`trigger`, `evidence`, `decision`, `guard`, `execution`, `observed`) to `retailtwin.agent_action_audit`. One `correlation_id` is one trace. A denial has no execution or observed row. `predicted_impact` is the decision's own `kpi_score`, and `-1.0` stays unscored. The reason is a short summary, not a prompt. A repeated payload is a duplicate and a different payload does not replace the row. The day-0 `agent_actions` table is unchanged. No route calls it, and it does not write the Live Twin. The BigQuery table is created only by `infrastructure/gcp/apply-agent-action-audit.sh` when `CONFIRM_GCP_AGENT_AUDIT=yes`;
- autonomous investigations for gate G03 (#50, ADR 0023). With `AUTONOMY_ENABLED=true`, `POST /events` hands each new `sale.completed` to the Observer. A background run then investigates, plans, and records a `pending` proposal and its Decision for the approve route. Each stage is a `GET /agent/events` entry with the event's correlation id. It never writes the Live Twin. The default is off. `GET /agent/events` and `GET /simulations/{id}/candidates` no longer return 500;
- one Gemini inventory read for issue #2 (ADR 0021) in `apps/api/retailtwin_api/agents/orchestrator/inventory_read.py`. `read_inventory` asks the injected provider for exactly one `get_inventory` call and executes it with `READ` granted. The request does not offer a simulation or commit tool. The typed Live Twin document is the result; model prose is ignored. A missing SKU returns `not_found`. No call, another tool, or another SKU fails closed. The Vertex adapter sends `functionCallingConfig` for that choice. CI uses `FakeLlmProvider`. A live call on 2026-10-14 with `gemini-2.5-flash` in `us-central1` read `store-001` / `P001` (shelf `A01`, slot `A01-S01`, 5 facings, 18 on the shelf, 42 in the backroom, version 3) and the tool output matched that Firestore document. An unknown SKU returned `not_found` and was not created. This does not write the Live Twin, does not call Vertex from Cloud Run, and does not pass foundation gate #10 or gates G02–G06;
- deterministic `sale.completed` publisher. The lander claims each `event_id` in Firestore `store_event_claims`. The landing lease chooses who may submit the derived insert, and that insert uses one BigQuery job id for the claim generation, so a takeover joins the same job. A replay of the same payload is a duplicate. A different payload is a conflict and does not replace the claim or the row. `correlation_id` is kept on the message and the row. A rejected message is quarantined before it is acknowledged;
- 3D move cue of issue #23 in `apps/web`. When the twin state on screen moves a product, its items hop from the source slot to the destination, an outline marks where it stood, and the light hands over from the source slot to the destination, flashes on arrival and fades out, and the product card says where it came from. The cue is read from the state diff (#91), so it shows for Live changes and for the Simulation view against Live, and leaving a proposal plays the move back;
- 3D facings cue for issue #24 in `apps/web`. Cap facings at slot capacity, flag overflow, and cue changes;
- 3D replenishment cue for issue #25 in `apps/web`. A recent stock change shows `Shelf +N` / `Backroom -N` on the product card and details dialog and glows on the slot of a shelf gain; a change that is not a matching backroom → shelf transfer is flagged as `inconsistentTransfer` until the next change; shelf units past what the facings hold show as `+N not shown`. Works in the Live and Simulation views under `?twin=memory|demo`;
- 3D selection, highlight, details cards, and camera focus for issue #22 in `apps/web`. Agent-driven camera focus and Follow agent (issue #28);
- canonical Firestore Live Twin boundary for issues #6 and #81 (PR #106) in `apps/api/retailtwin_api/twin/live_twin.py`. Versioned SKU documents, atomic commits with Firestore preconditions, and ADC auth;
- provider-neutral LLM runtime for issue #85 (ADR 0008) in `apps/api/retailtwin_api/llm/`. Registered providers (`fake`, `openai_compatible`, `vertex_gemini`), adapter pattern, production requires `vertex_gemini` with ADC;
- deterministic KPI evaluator for issue #33 (PR #112) in `services/simulation`. Score candidates with stockout risk, service level, movement cost, and business score;
- simulation clone scoring for issue #15 (PR #173). Apply candidate actions to a clone, score the result;
- Day-0 FastAPI Cloud Run deployment for issue #9 (PR #111). Linux/amd64 image, gcr.io/retailtwin-ai-511002/retailtwin-api, public invoker, minimum instances 1;
- production Cloud Run hardening for issue #34 (PR #113). WIF/OIDC authentication, secret management, health/degraded status;
- simulation review routes for issues #83 (PR #127). `POST /simulations/{id}/approve` and `/simulations/{id}/reject` with HMAC-signed authorization;
- simulation candidate details and production API binding for issue #93 (PR #158). Wire candidates to proposal view;
- analytics routes for issues #79 and #74 (PR #129). `GET /anomalies`, `/revenue`, `/promotions` with Firestore and BigQuery backends;
- simulation API routes for issue #32 (PR #151). In-memory SimulationRepository for `/simulations` routes;
- verify post-action state for issue #19 (PR #167). Re-read live inventory after commit;
- commit through signed single-use authorization for issue #18 (PR #166);
- no-stale-commit for issue #17 (PR #152). Binding expiry enforcement, immutable audit;
- refresh evidence and replan after stale rejection for issue #20 (PR #168);
- record agent-action provenance in BigQuery for issue #35 (PR #177). Agent-action audit trail;
- bounded automatic rollback policy for issue #55 (PR pending, ADR 0039). Off by default until G06 evidence;
- reproducible G04 guard-gate evidence for issue #51 (PR #176). Fix reused ids after replan;
- Firebase Hosting CD pipeline for issue #43 (PR #162). Web deployment via Firebase Hosting;
- health/degraded status and graceful analytics degradation for issue #44 (PR #157);
- error boundary and retry recovery for issue #44 (PR #160);
- demo mode with `VITE_ALLOW_DEMO` and GLB stock models for issue #29 (PR #180);
- closed-up exterior with roof, sky, decor and street grid for issue #29 (PR #180);
- merge-conflict markers CI for issue #133 (PR #147). Block merge-conflict markers in every change;
- security CI for issues #146 and #188. Secret/dependency and container scans before deploy;
- Cloud Run deployment verification for issue #187. Verify public Cloud Run deployment;
- ADR 0001, 0002, 0003, 0004, 0005, 0006, 0007, 0008, 0009, 0010, 0011, 0012, 0014, 0015, 0016, 0017, 0018, 0019, 0020, 0021, and 0039;
- tracked `apps/web/package-lock.json`.

## Google Cloud foundation

Issue #5 applies the shared project `retailtwin-ai-511002` in `us-central1`. The shape is the always-free layout in [infrastructure/gcp/README.md](../infrastructure/gcp/README.md) and [ADR 0004](adr/0004-keep-the-cloud-foundation-on-free-tier.md): required APIs on, Compute Engine and the other large services off, two service identities and no keys. Firestore `(default)` is Standard edition Native mode. The Live Twin is seeded from Firestore documents on `main` via PR #106.

The API runs on Cloud Run (issue #9, PR #111) with public invoker, minimum instances 1, and WIF/OIDC authentication (issue #34, PR #113). The deployed service accepts `GET /health`, `/ready`, `/store` without credentials.

The monthly budget `retailtwin-dev-guard` is 25,000 VND, about 1 USD, on this project only, with alerts at 50%, 90%, and 100%. The billing account currency is VND. The alert does not disable billing.

## Work in progress

Issue #134 (cloud-config) is merged via PR #185. It owns the canonical production cloud runtime matrix, service-account naming, Artifact Registry path reconciliation, WIF/CI deployment configuration, Secret Manager contract, and `.env.example` update. It does not implement the runtime wiring itself; that contract is verified once the issue merges.

Issue #135 (demo-data) is in progress on branch `issue/135-demo-data` via active implementation PR #197. It provides a deterministic GCP seed/reset/replay workflow for Firestore, BigQuery, and Pub/Sub using the P017 Weekend Demand Surge scenario and P001 foundation data. Checkout, payment, and promotion production datasets are not in scope until their respective backend contracts land.

Issue #58 is closed. The web build and test workflow is on `main`.

Issue #60 is closed (PR #68). Coverage instrumentation is in place and running in CI.
Behavior tests exist. There is no hard coverage gate yet, so a passing test count is not
a coverage percentage. Coverage is measured; threshold enforcement is phase 2 before
Foundation Gate #10.

Baseline (PR #68):
- API: 89% line, 85% branch (pytest-cov, 269 stmts, 44 branches)
- Web: 91% stmt/line, 91% branch (Vitest v8, 12 tests)

## Implemented on main

The following have been implemented since the 2026-10-08 baseline:

- Firestore-backed Live Twin and seed/reset (issue #6, PR #106);
- Cloud Run production deployment (issue #9, PR #111, #113);
- Provider-neutral LLM runtime (issue #85, PR #109);
- Deterministic KPI evaluator (issue #33, PR #112);
- Simulation clone scoring (issue #15, PR #173);
- Simulation review routes — POST /approve and /reject (issue #83, PR #127);
- Simulation candidate binding (issue #93, PR #158);
- Simulation API routes (issue #32, PR #151);
- Analytics API — GET /anomalies, /revenue, /promotions (issues #79, #74, PR #129);
- Agent-action audit trail (issue #35, PR #177);
- Guard-gate reproducible evidence (issue #51, PR #176);
- Verifier post-action state check (issue #19, PR #167);
- Commit through signed authorization (issue #18, PR #166);
- No-stale-commit enforcement (issue #17, PR #152);
- Auto re-plan on stale rejection (issue #20, PR #168);
- Bounded automatic rollback policy (issue #55, PR pending, off until G06);
- Firebase Hosting CD (issue #43, PR #162);
- Health/degraded status (issue #44, PR #157);
- Error boundary (issue #44, PR #160);
- Demo mode with GLB models (issue #29, PR #180);
- 3D move cue (issue #23, PR #115);
- 3D facings cue (issue #24, PR #116);
- 3D replenishment cue (issue #25, PR #117);
- 3D selection and highlight (issue #22, PR #118);
- Agent-driven camera focus (issue #28, PR #126);
- Merge-conflict markers CI (issue #133, PR #147);
- Security CI with container scans (issues #146, #188);
- Cloud Run deployment verification (issue #187).

## Not implemented yet

Do not infer implementation merely because a component is documented in the target architecture. The following remain planned/open unless their issue is explicitly completed:

- Later analytical tables such as product performance and simulation results;
- end-to-end autonomous scenario;
- Demo data for production build (issue #135, active PR #197);
- submission gates G02–G06.

## Current release-gate status

| Gate | Status | Evidence required |
| --- | --- | --- |
| Day-0 / Foundation #10 | NOT PASSED | integrated web + API + Firestore + Pub/Sub + Gemini tool + Cloud Run smoke test |
| G02 Twin Control #49 | NOT PASSED | agent tool changes Simulation Twin + 3D while Live remains unchanged |
| G03 Autonomous #50 | NOT PASSED (API evidence harness: `tests/e2e/gates/g03_autonomous_gate.py`) | store event starts agent without prompt; Pub/Sub trigger and production read ports for non-inventory sources still open |
| G04 Guard #51 | NOT PASSED (API evidence harness: `tests/e2e/gates/g04_guard_gate.py`) | stale decision is rejected and cannot mutate Live Twin; UI view of the rejection is #40 |
| G05 Live Commit #52 | NOT PASSED (API evidence harness: `tests/e2e/gates/g05_live_commit_gate.py`) | valid guarded decision changes Live Twin and 3D; rendered 3D frame and observed post-action KPI not yet captured |
| G06 Submission #53 | NOT PASSED | 20 consecutive flagship E2E runs |

Gate status changes only when the corresponding issue contains reproducible evidence and is closed intentionally.

## Immediate critical path

1. Issue #58 is closed. The web build and test workflow is on `main`. Issue #60 adds the coverage baseline and threshold to that gate.
2. The Firestore Live Twin boundary is on `main` (issue #6, PR #106). The scene reads `GET /store` from `apps/api` and places products on the layout (ADR 0007). The scene polls `GET /store` every 5 s. When reads fail, it backs off up to 60 s. It keeps the last state, or empty shelves, on screen when the API is down.
3. Cloud Run production wiring for Vertex AI with ADC (Foundation #10) is pending runtime evidence. The `vertex_gemini` provider name cannot be replaced or removed (ADR 0020). The cloud-config config/runtime-matrix (issue #134, merged via PR #185) owns the canonical production cloud runtime matrix, WIF/CI deployment configuration, and Secret Manager contract; it does not implement the runtime wiring itself.
4. The allow-listed tool registry (#11, ADR 0009), the observer (#12, ADR 0010), the investigator (#13, ADR 0011), the planner (#14, ADR 0012), the Decision Context Guard with No-Stale-Commit (#16, ADR 0014 and #17, ADR 0015), the guarded Executor (#18, ADR 0016), the post-action Verifier (#19, ADR 0017), and automatic re-plan (#20, ADR 0018) are in the API. Simulation clone scoring (#15) evaluates candidates. Provider selection is a registry (ADR 0020): production construction requires Vertex ADC, uses the shipped Vertex builder, and rejects a fake provider, a loopback endpoint, and an API key. The `vertex_gemini` name cannot be replaced or removed. The one Gemini read is `read_inventory` (ADR 0021). The agent-action audit (#35, ADR 0019) records the correlated trace. Gates G02–G06 and foundation gate #10 stay unpassed.
5. Bind state changes to the 3D Live/Simulation views. The 3D move, facings, and replenishment cues are implemented. The 3D binding to Live/Simulation Twin state is wired through the state diff (#91).
6. Pass G02 → G03 → G04 → G05 → G06 in order.

## Documentation rule

Use these terms consistently:

- **Implemented/current** means code exists on `main` and has appropriate verification.
- **In progress** means an open PR exists but is not yet part of `main`.
- **Target/planned** means architecture or issue scope only.
- **Gate passed** means the gate issue has reproducible evidence and is closed.

Narrative architecture documents describe the target product. This file describes the repository's current maturity and must be updated whenever a release gate changes or a major subsystem lands.
