# RetailTwin AI — Current Project Status

**Status date:** 2026-10-07  
**Purpose:** separate what is implemented now from the target architecture described elsewhere.

## Current baseline on main

The repository currently contains a working **view-only 3D web scaffold** merged through PR #56 / issue #3.

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
- reserved Agent Activity panel;
- ADR process with ADR 0001 and 0002.

The current 3D fixture is **not Live Twin truth**. It is intentionally a view fixture until issue #4 binds the scene to API/Firestore-backed Digital Twin state.

## Work in progress

PR #57 implements the FastAPI/frontend integration scope for issue #8. It is not part of `main` yet. The branch has been reconciled with the current `main`, GitHub reports it as mergeable, it preserves the #56 3D scene, and it integrates `StoreStatus` through `AgentActivityPanel`.

Its intended boundary is:
- `GET /health`;
- `GET /store`;
- `GET /inventory/{sku}`;
- `POST /events`;
- typed frontend API client/status UI;
- fixture-backed reads as a scaffold, not Firestore Live Twin.

Issue #58 tracks the remaining reproducibility/CI work. PR #57 now commits `apps/web/package-lock.json`, so the dependency-lock input exists on that branch, but there is still no executable GitHub Actions build/test gate or check run on the current project baseline. #58 remains open until CI exists and is green.

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

1. Finish the remaining review fixes in PR #57 and merge only after the event-ID integrity issue is resolved.
2. Resolve #58 by adding a green executable CI build/test gate; the lockfile portion is already present in PR #57.
3. Complete Firestore (#6), Pub/Sub/BigQuery (#7), Gemini real read tool (#2), Cloud Run (#9).
4. Pass Foundation Gate #10.
5. Continue the autonomous path: Tool Registry → Observer → Investigator → Planner → Simulation → DCG → Executor → Verifier.
6. Bind those state changes to the 3D Live/Simulation views.
7. Pass G02 → G03 → G04 → G05 → G06 in order.

## Documentation rule

Use these terms consistently:

- **Implemented/current** means code exists on `main` and has appropriate verification.
- **In progress** means an open PR exists but is not yet part of `main`.
- **Target/planned** means architecture or issue scope only.
- **Gate passed** means the gate issue has reproducible evidence and is closed.

Narrative architecture documents describe the target product. This file describes the repository's current maturity and must be updated whenever a release gate changes or a major subsystem lands.
