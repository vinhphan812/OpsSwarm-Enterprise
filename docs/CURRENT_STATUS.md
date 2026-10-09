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
- `POST /events` does not change inventory and does not write Live Twin state;
- ADR 0001, 0002, and 0003;
- tracked `apps/web/package-lock.json`.

The 3D scene and the API are **not Firestore Live Twin**. Issue #4 binds the scene to twin state. Issue #6 replaces `open_store` with Firestore and keeps the four routes.

## Google Cloud foundation

Issue #5 applies the shared project `retailtwin-ai-511002` in `us-central1`. The shape is the always-free layout in [infrastructure/gcp/README.md](../infrastructure/gcp/README.md) and [ADR 0004](adr/0004-keep-the-cloud-foundation-on-free-tier.md): required APIs on, Compute Engine and the other large services off, two service identities and no keys, and empty free-tier resources. Firestore `(default)` is Standard edition Native mode with no documents. There is no Pub/Sub subscription, no BigQuery table, no Cloud Run service, and no Gemini call.

The monthly budget `retailtwin-dev-guard` is 25,000 VND, about 1 USD, on this project only, with alerts at 50%, 90%, and 100%. The billing account currency is VND. The alert does not disable billing.

## Work in progress

Issue #58 remains open. The web lockfile is on `main`. An executable GitHub Actions build/test gate is not. #58 stays open until that gate exists and is green.

Issue #60 remains open. Behavior tests exist. There is no coverage instrumentation or threshold, so a passing test count is not a coverage percentage. #60 owns that baseline and the CI coverage gate.

## Not implemented yet

Do not infer implementation merely because a component is documented in the target architecture. The following remain planned/open unless their issue is explicitly completed:

- Firestore-backed Live Twin and seed/reset;
- BigQuery analytical tables and audit trail;
- Pub/Sub autonomous event pipeline;
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

1. Resolve #58 with a green executable GitHub Actions CI build/test gate. The web lockfile is already on `main`. Issue #60 then adds the coverage baseline and threshold to that gate.
2. Complete Firestore seed (#6) in the existing `(default)` database, Pub/Sub/BigQuery (#7), Gemini real read tool (#2), and Cloud Run (#9).
3. Pass Foundation Gate #10. #10 stays open: Firestore, Pub/Sub, Gemini real tool use, and Cloud Run are still required.
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
