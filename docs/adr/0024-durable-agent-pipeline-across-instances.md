# 0024. Persist the autonomous agent pipeline across instances

Date: 2026-10-16

## Status

Proposed

## Context

ADR 0023 wired Pub/Sub events to the FlagshipController so a `sale.completed` starts an investigation, plans a decision, and (after the guarded approve route) commits through the Executor. The pipeline runs entirely in process memory: `MemoryPipe`, `MemoryActivationLedger`, `MemoryQuarantine`, `InMemoryDecisionSource`, the process-local `AgentActivityLog`, and the in-process `SimulationRepository`.

Cloud Run can run multiple instances of the API. The first instance may receive an event, run the chain, and stop responding while the second instance — or a new revision after a deploy — still serves `GET /simulations/{id}/approve` and `GET /agent/events`. Today those reads return 503 (`decisions.available == False`) and an empty activity feed because nothing is shared across instances.

Issue #217 ([P0][AGENT-E2E]) calls for one durable `event_id → run_id → decision_id → simulation_id` trace so the judge-visible evidence can be reproduced after a deploy. The same issue requires:
- durable Pub/Sub intake/ack + idempotent correlation;
- `decision_id`, `simulation_id`, `context_version` on every step;
- investigator evidence backed by Firestore + BigQuery;
- planner through Vertex Gemini via the constrained tool registry;
- Simulation only — Live untouched until guarded `ALLOW`;
- persistent Agent Activity events and audit provenance (no model reasoning or secrets);
- explicit recovery for bad payload, insufficient evidence, Vertex error, stale plan, duplicate event, and process restart.

Three alternatives were considered:

- **Per-instance SQLite/Postgres** as a shared store. Adds an extra dependency, a deploy-time migration path, and a managed-instance IAM surface that the project does not need.
- **BigQuery-only writes** for every state. Cost and latency make it unsuitable for the hot path that backs `GET /simulations/{id}/approve` (a single-digit-millisecond read on a Cloud Run request).
- **Firestore for the canonical state**, `agent_action.yaml` and `store_events` BigQuery tables unchanged (ADR 0019). Project Firestore is already provisioned (ADR 0004), already backs `GET /store` / `GET /inventory/{sku}` (issue #6, ADR 0003), and offers an `updateTime` precondition that maps cleanly onto the same `version + 1` invariant the Executor enforces.

## Decision

The pipeline keeps its current in-memory adapters for tests and dev, and adds four Firestore-backed adapters that share the same Protocol surface:

| Component | Process-memory adapter (tests + dev) | Durable adapter (Firestore) | Document path |
| --- | --- | --- | --- |
| Decision mapping | `InMemoryDecisionSource` (`decisions.py`) | `FirestoreDecisionSource` | `decision_records/{simulation_id}` |
| Simulation state | `SimulationRepository` (`simulation.py`) | `FirestoreSimulationRepository` | `simulation_records/{simulation_id}` |
| Agent Activity feed | `AgentActivityLog` (`agent_activity.py`) | `FirestoreAgentActivityLog` | `agent_activity/{entry_id}` (append-only, monotonic id) |
| Activation ledger | `MemoryActivationLedger` (`agents/observer/consumer.py`) | `FirestoreActivationLedger` | `activation_records/{event_id}` (idempotency key) |

`create_app` keeps the in-memory defaults for `LIVE_TWIN_BACKEND in {"fixture", "memory"}`. When `LIVE_TWIN_BACKEND == "firestore"`, the same factory wires the Firestore adapters using the existing `FirestoreLiveTwinRepository` client, so a production deploy never falls back to a process-memory store silently. The selection rule is a single `get_persistence(settings)` factory in `retailtwin_api/persistence.py`; main.py calls it once and assigns the four adapters to `app.state`. There is no per-instance memory wiring in production.

Each Firestore adapter follows three rules:

1. **Fail closed.** `FirestoreDecisionSource.put` writes through the same `FirestoreLiveTwinRepository.updateTime` precondition so a parallel `approve` cannot regress the stored record. The adapter raises `DecisionStoreUnavailable`; the chain treats that as a `failed` Agent Activity entry and does not start a second investigation.
2. **No secrets, no model reasoning.** Adapters serialize the canonical Pydantic model only. The Decision JSON never includes a `vertex_*` field, prompt, or credential.
3. **Idempotent writes.** `put` and `record` use the document id as the idempotency key. Re-delivered events from Pub/Sub re-write the same document with the same payload and produce no observable change.

Investigator evidence gains a BigQuery-backed `get_sales_history` port. The port reads `retailtwin.sales_events` for the canonical store/SKU window (Friday + Saturday + recent movement) and is bound through the existing `bind_read_port` (`agents/investigator/evidence.py`). The Investigator treats an unavailable BigQuery as `source_unavailable` — never invents a number — and surfaces that as `INSUFFICIENT_EVIDENCE`. The hard-coded P017 figures in issue #215 stay in tests only; the production path reads them from rows.

The Planner keeps `Vertex` so the tool registry routes the call through `vertex_gemini` per ADR 0020. The factory's pre-flight (`create_provider(vertex_gemini, ...)`) is unchanged: a missing ADC or wrong project refuses to build, and the chain records `provider_failed` (typed `InvestigatorError` / `PlannerError`) instead of falling back to the fake adapter.

Failure recovery is typed. `observe_message` returns one of `started`, `duplicate`, `conflict`, `ignored`, `rejected`, `insufficient_evidence`, `provider_failed`, `stale_plan`. Pub/Sub is acked on every terminal outcome except `rejected` (which quarantines) and `provider_failed` (which leaves the activation ledger's reservation so the message is re-delivered after the Vertex outage clears). The chain never silently retries in-process; the durable adapters carry state across the retry boundary.

`GET /simulations/{id}/approve` reads from `FirestoreDecisionSource`; `GET /agent/events` reads from `FirestoreAgentActivityLog`; `GET /simulations` reads from `FirestoreSimulationRepository`. All three routes already exist; the storage swap is the only behavioral change. The PR keeps the process-memory adapters in tests (no firestore emulator in CI yet) and adds fixture-backed unit tests for every Firestore adapter using the same FakeFirestore the existing `firestore_twin.py` tests use.

## Consequences

- **Cross-instance durability.** A second Cloud Run instance can answer `GET /simulations/{id}/approve` and `GET /agent/events` for a run completed on the first. The `event_id → run_id → decision_id → simulation_id` chain is reproducible after a deploy.
- **Vertex is the only LLM.** No code path in production can build a `fake` or `openai_compatible` provider. A misconfigured Vertex build disables the airport, the API stays up, and the activity feed records `provider_failed`.
- **BigQuery is the canonical evidence.** The hard-coded P017 figures from issues #30/#31/#32 leave production code and become test fixtures. A real run reads the window from rows and surfaces `source_unavailable` when BigQuery is empty or unavailable.
- **No new external service.** The pipeline reuses the existing Firestore database, the existing `FirestoreLiveTwinRepository`, and the existing `sales_events` BigQuery table (ADR 0005, #197). No Terraform, no new service account, no extra secret.
- **Failure is observable.** Every failure mode becomes a typed Agent Activity entry, a `failed` investigation result, or a quarantine row. Pub/Sub acks happen on terminal outcomes so a duplicate never starts two investigations and a transient Vertex outage does not silently drop the run.
- **Cloud Run deploy unchanged.** The same `scripts/deploy-cloudrun.sh` (issue #9) deploys the same image; the only new requirement is `LIVE_TWIN_BACKEND=firestore` in the production env. The release gate (`release-gate.yml`, #145) verifies that env on the deployed service.
- **Follow-up work.** Issue #214 (production composition root) becomes a small wiring change inside `create_app`. Issue #215 (BigQuery evidence) lands as the `get_sales_history` port implementation this record calls for. Issue #216 (deployed data verification) becomes the post-deploy evidence that exercises the durable pipeline.

- Pull request:
- Issue: #217
- Supersedes:
- Superseded by: