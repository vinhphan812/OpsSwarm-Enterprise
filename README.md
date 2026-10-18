# RetailTwin AI

**Context-Guarded Autonomous 3D Retail Digital Twin**

RetailTwin AI is an autonomous retail-operations system built around a live 3D Digital Twin of a store. A real store event (a sale spike, an inventory change, a promotion) triggers an AI control loop that gathers versioned evidence, plans bounded candidate actions, scores them on an isolated Simulation Twin, validates the selected decision with a deterministic Decision Context Guard (DCG), and only then commits the exact authorized actions to the Live Twin. A post-action Verifier re-reads Live Twin rows and reports `VERIFIED`, `REGRESSION`, or `INCONCLUSIVE`. The 3D view is the Live Twin, not a decoration.

> **The LLM never owns the store state.** The Digital Twin owns truth. Gemini reasons over that truth and acts only through constrained, allow-listed tools ([ADR 0009](docs/adr/0009-expose-one-allow-listed-tool-registry.md)). The guarded Executor is the only code that mutates the Live Twin ([ADR 0016](docs/adr/0016-commit-only-through-a-signed-single-use-authorization.md)).

## Problem

Retail conditions change between the moment an AI makes a decision and the moment that decision reaches a live system. Existing tools are mostly reactive:

- **Dashboards** tell a store manager what already happened. They do not act.
- **Chatbots** wait for a human prompt. The prompt may come long after the opportunity is gone.
- **Generic LLM agents** can produce a sensible plan at time T and an invalid one at T+1, because inventory, facings, promotions, or backroom state has moved on. Nothing in the loop re-validates the plan at the commit moment.

RetailTwin AI closes those three gaps: it is autonomous (events drive the loop, no prompt is required), it is grounded in a 3D Digital Twin (zones, shelves, slots, products and inventory are explicit entities), and it is safe at commit time (No-Stale-Commit re-reads the Live Twin immediately before mutation and blocks the plan if relevant state changed).

## Solution

The autonomous control loop is a single deterministic state machine:

```text
OBSERVE → DETECT → INVESTIGATE → PLAN → SIMULATE → GUARD → ACT → VERIFY
```

In the competition story:

```text
EVENT → AI → INVESTIGATE → SIMULATE → GUARD → LIVE 3D ACTION → VERIFY
```

For each event the loop does the following:

1. **Observe** — A normalized `sale.completed` (or other store event) lands on Pub/Sub and is consumed by the Observer without a human prompt ([ADR 0010](docs/adr/0010-start-one-investigation-per-sale.md)).
2. **Investigate** — Versioned evidence is collected through the allow-listed tool registry ([ADR 0011](docs/adr/0011-collect-versioned-evidence-from-the-tool-registry.md)).
3. **Plan** — Gemini on Vertex AI proposes two or three bounded candidate actions ([ADR 0012](docs/adr/0012-bind-candidate-plans-to-the-evidence-context.md)). Gemini never invents KPI numbers.
4. **Simulate** — Each candidate is applied to a Simulation Twin clone and scored by the deterministic `simulation-kpi-v1` evaluator ([ADR 0013](docs/adr/0013-score-candidate-plans-on-a-simulation-clone.md)). The Live Twin is not touched.
5. **Guard** — The Decision Context Guard runs six deterministic gates in order and returns one of `ALLOW`, `DENY`, `REFRESH_REQUIRED`, or `HUMAN_REVIEW` ([ADR 0014](docs/adr/0014-guard-each-decision-with-deterministic-gates.md)). No-Stale-Commit re-runs the same gates immediately before commit and refuses any decision whose touched SKU version changed ([ADR 0015](docs/adr/0015-recheck-live-versions-before-every-commit.md)).
6. **Act** — A short-lived HMAC-signed single-use authorization is bound to the decision id, the context hash, the exact action hashes, and the live versions of every touched SKU. The guarded Executor redeems the token, re-runs the guard, and writes every touched SKU plus the store version step in one atomic Firestore commit ([ADR 0016](docs/adr/0016-commit-only-through-a-signed-single-use-authorization.md)).
7. **Verify** — The Verifier re-reads each touched SKU through the Live Twin and reports `VERIFIED`, `REGRESSION`, or `INCONCLUSIVE` ([ADR 0017](docs/adr/0017-verify-post-action-state-by-rereading-live-inventory.md)).
8. **Recover** — On `REFRESH_REQUIRED` the orchestrator discards the binding, refreshes evidence with the same provider, and replans under a bounded refresh budget ([ADR 0018](docs/adr/0018-refresh-evidence-and-replan-after-a-stale-rejection.md)).

The agent can therefore demonstrate a clean stale-context block followed by an automatic recovery and a successful guarded commit, all without a human in the loop.

## Architecture

The full architecture, including the data flow, the LLM-provider-neutral contract, the DCG gate definitions, and the Live-vs-Simulation boundary, is in:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — end-to-end component map, gate definitions, and security rules.
- [docs/architecture/README.md](docs/architecture/README.md) — canonical autonomous control loop diagram (delivered in issue #46 in parallel; cross-referenced here once the diagram lands).
- [docs/DOMAIN_AND_DATA_MODEL.md](docs/DOMAIN_AND_DATA_MODEL.md) — `Store → Zone → Shelf → Slot → Product` model, event envelope, EvidenceBundle, action contracts, and Live/Simulation isolation.
- [docs/adr/](docs/adr/README.md) — the architecture decision log. Every record lists the issue and pull request that adopted it.

## Flagship scenario

The flagship scenario is **Weekend Demand Surge** on `store-001` / `P017`. A SKU begins to sell faster than its baseline. Pub/Sub carries each `sale.completed` to the Observer, which starts an investigation. The Investigator reads shelf quantity, backroom quantity, and sales velocity through the tool registry. The Planner proposes two or three candidate actions, for example: (A) replenish only, (B) increase facings and replenish, (C) relocate a lower-performing SKU and increase facings and replenish. Each candidate is scored on a Simulation Twin clone. The selected decision is bound to its context version and sent to DCG.

For the signature demo, relevant Live Twin state is mutated between planning and commit. DCG detects that the decision was built at version N and the SKU is now at N+1, returns `REFRESH_REQUIRED`, and blocks the commit. The agent automatically refreshes evidence, replans, and resubmits. The new decision passes, an HMAC-signed authorization is issued, the guarded Executor commits, the 3D view updates, and the Verifier reports `VERIFIED`. Detailed steps, Mermaid sequence, and judge-visible evidence are in [docs/DEMO_AND_ACCEPTANCE.md](docs/DEMO_AND_ACCEPTANCE.md).

## AI and Google Cloud integration

RetailTwin AI uses Google AI and Google Cloud as its inference layer, operational data plane, and runtime:

| Layer | Google Cloud / Google AI service | Role |
|---|---|---|
| LLM inference | **Gemini on Vertex AI** — `gemini-2.5-flash` in `us-central1` | Evidence interpretation, structured candidate plans, natural-language summaries. The shipped adapter name is `vertex_gemini`; production requires Application Default Credentials and refuses a fake provider, a loopback endpoint, or an API key ([ADR 0020](docs/adr/0020-register-llm-providers-and-require-vertex-adc-in-production.md)). The single live read is `get_inventory` ([ADR 0021](docs/adr/0021-require-one-gemini-inventory-read.md)). |
| Live Digital Twin | **Firestore** (Native, Standard, `(default)`) | Versioned SKU documents, atomic commits with `updateTime` preconditions, and the canonical `store_event_claims` event-id ledger. |
| Analytics and history | **BigQuery** dataset `retailtwin` in `us-central1` | `sales_events`, `inventory_events`, `agent_actions`, and `agent_action_audit` (one row per stage, correlated by `correlation_id` per [ADR 0019](docs/adr/0019-record-agent-action-provenance-in-bigquery.md)). |
| Event backbone | **Pub/Sub** topic `store-events`, subscription `store-events-analytics` | Event-driven activation. Every event carries `event_id`, `correlation_id`, `event_type`, and `store_id` ([ADR 0005](docs/adr/0005-land-each-normalized-store-event-once.md)). |
| Runtime | **Cloud Run** service `retailtwin-api` in `us-central1` | FastAPI on the `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` runtime identity. Deployed from Artifact Registry. |
| CI/CD | **Workload Identity Federation** to `github-actions@...` | Keyless deploys; no long-lived JSON keys. |
| Static assets | **Cloud Storage** `gs://retailtwin-ai-511002-assets` | 3D models and decor. |
| Web hosting | **Firebase Hosting** `retailtwin-ai-511002.web.app` | Production web delivery. |

The full canonical resource table (exact names, regions, IAM roles, environment variables, verification commands) is in [docs/CLOUD_RUNTIME_MATRIX.md](docs/CLOUD_RUNTIME_MATRIX.md).

## Safety

Every autonomous action is protected by a stack of small, deterministic, individually testable safety mechanisms:

- **Decision Context Guard (DCG)** — six deterministic gates in order: integrity, evidence sufficiency, per-SKU context version, freshness within `RETAILTWIN_DCG_FRESHNESS_SECONDS` (default 120), physical and business feasibility, and policy. The first failure decides. The guard reads the Live Twin, never writes it, and imports no model SDK ([ADR 0014](docs/adr/0014-guard-each-decision-with-deterministic-gates.md)).
- **No-Stale-Commit** — wraps the guard so a decision built at version N is `REFRESH_REQUIRED` once a touched SKU is at N+1, and an altered action list is `DENY BINDING_MISMATCH`. Each call records a `GuardAuditEvent` ([ADR 0015](docs/adr/0015-recheck-live-versions-before-every-commit.md)).
- **Signed single-use authorization** — HMAC-SHA256 token bound to the decision id, context hash, the SHA-256 of each canonical action, the live version of every touched SKU, a 128-bit nonce, and a 30-second expiry. A missing, tampered, expired, reused, or action-mismatched token changes nothing ([ADR 0016](docs/adr/0016-commit-only-through-a-signed-single-use-authorization.md)).
- **Guarded Executor** — the only production code that commits an agent decision. Redeems the token, re-runs the guard, and writes every touched SKU plus the store version step in one atomic Firestore commit with `updateTime` preconditions ([ADR 0016](docs/adr/0016-commit-only-through-a-signed-single-use-authorization.md)).
- **Post-action Verifier** — re-reads each touched SKU through the Live Twin and reports `VERIFIED`, `REGRESSION`, or `INCONCLUSIVE`. Does not call the KPI evaluator again and does not write the Live Twin ([ADR 0017](docs/adr/0017-verify-post-action-state-by-rereading-live-inventory.md)).
- **Bounded retry** — the orchestrator refreshes evidence and replans on `REFRESH_REQUIRED` under `RETAILTWIN_REPLAN_MAX_REFRESHES` (default 1). A provider, planner, simulation, or commit failure stops the run without another refresh and without a second live attempt. The production composition root binds the failure-recovery contract end-to-end ([ADR 0018](docs/adr/0018-refresh-evidence-and-replan-after-a-stale-rejection.md), [issue #214](https://github.com/vinhphan812/retailtwin-ai/issues/214)).
- **Provenance** — every stage of one autonomous run is written to `retailtwin.agent_action_audit` with the same `correlation_id`. A denial has no execution or observed row. No model chain-of-thought, no credentials ([ADR 0019](docs/adr/0019-record-agent-action-provenance-in-bigquery.md)).

The full set of safety invariants, with code pointers, is in [docs/ARCHITECTURE.md §4](docs/ARCHITECTURE.md#4-decision-context-guard).

## Setup

### API (Python 3.11+)

```bash
cd apps/api
pip install -e ".[dev]"
```

The API reads its non-secret configuration from environment variables. Copy [`.env.example`](.env.example) to `.env` and adjust as needed. **Do not commit `.env`.** No service-account key, Gemini API key, or Google API key goes into the file; development uses the `fake` provider, production uses `vertex_gemini` with ADC ([ADR 0020](docs/adr/0020-register-llm-providers-and-require-vertex-adc-in-production.md)).

Required environment variables are documented inline in [`.env.example`](.env.example) and in the canonical table at [docs/CLOUD_RUNTIME_MATRIX.md](docs/CLOUD_RUNTIME_MATRIX.md). The runtime recognises three Live Twin backends: `memory` (in-process, default for local dev), `firestore` (production), and `fixture` (read-only, used by the day-0 API).

### Web (Node 20+)

```bash
cd apps/web
npm ci
```

The web build reads `VITE_API_BASE_URL` from `apps/web/.env.local` (created by copying from `.env.example`). The day-0 API is `http://127.0.0.1:8000`; the production Cloud Run URL is set in CI.

### Google Cloud authentication

The day-0 API does not need GCP credentials. The local API serves the committed fixture at `data/schemas/store-state.example.json` and does not mutate live inventory.

To run against the real Live Twin, configure Application Default Credentials before starting the API:

```bash
gcloud auth application-default login
gcloud config set project retailtwin-ai-511002
```

For production deploys, Workload Identity Federation replaces the developer credential. See [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh) and the workflow contract in `.github/workflows/`.

### Verifying the foundation

```bash
./scripts/verify-cloud-preflight.sh        # read-only, no secrets printed
PYTHONPATH=apps/api python3 -m pytest apps/api/tests --no-header -q
```

The preflight script is the canonical read-only check for the cloud resources listed in [docs/CLOUD_RUNTIME_MATRIX.md](docs/CLOUD_RUNTIME_MATRIX.md).

## Deployment

Production deployment is performed by the committed script:

- [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh) — builds the Linux/amd64 image, pushes to Artifact Registry, deploys to Cloud Run `retailtwin-api` in `us-central1` on the `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` runtime identity, and verifies `/health`, `/ready`, and `/store`.
- [scripts/deploy-web.sh](scripts/deploy-web.sh) — builds the web bundle and publishes to Firebase Hosting `retailtwin-ai-511002.web.app`.

The shape and identity of every resource that Terraform (#99) will codify is in [docs/CLOUD_RUNTIME_MATRIX.md](docs/CLOUD_RUNTIME_MATRIX.md). Cloud Run revision rollback is documented inline in the deploy script. Service-account names, region, and CORS allow-list are non-secret and are part of the matrix; any drift must be reconciled through a new ADR.

## Demo

The flagship demo, the 3-minute storyboard, the stale-context acceptance, the 20-run Submission Gate, and the failure tests are in [docs/DEMO_AND_ACCEPTANCE.md](docs/DEMO_AND_ACCEPTANCE.md). Reproducible runnable evidence is in `tests/e2e/gates/g0{3,4,5}_*_gate.py` and `tests/e2e/test_g0{3,4,5}_*_gate.py`. Each harness writes a JSON evidence file with the run id, git SHA, decision ids, guard checks, before/after Live Twin state, and a per-step pass/fail entry.

## Limitations and current state

The README describes the system as designed and what is implemented on `main` today. Implementation status, the list of evidence harnesses, and the open work (Cloud Run production wiring for Vertex, G02–G06 release gates, demo data for the production build) are tracked in [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md). A diagram is not a claim that a release gate has passed. Gate status changes only when the corresponding issue contains reproducible evidence and is intentionally closed.

## License

This repository does not currently declare a license file. Add the chosen license at the repository root before public release.

## Documentation index

- [README.md](README.md) — this file.
- [docs/COMPETITION_README.md](docs/COMPETITION_README.md) — long-form technical brief with the deep-dive architecture, the 8-stage agent walkthrough, storage layout, and the gate evidence index.
- [docs/DOCS_INDEX.md](docs/DOCS_INDEX.md) — every document in the repository, with status and audience.
- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) — the retail problem, product behaviour, scope, glossary.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data flow, DCG, security, and Live/Simulation boundaries.
- [docs/architecture/README.md](docs/architecture/README.md) — canonical autonomous control loop diagram (issue #46, in progress).
- [docs/DOMAIN_AND_DATA_MODEL.md](docs/DOMAIN_AND_DATA_MODEL.md) — entities, schemas, events, evidence, tools, actions, KPIs.
- [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md) — role-by-role work and the build phases.
- [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md) — issue → branch → PR → ADR workflow and merge-safety rules.
- [docs/DEMO_AND_ACCEPTANCE.md](docs/DEMO_AND_ACCEPTANCE.md) — flagship scenario, stale-context acceptance, 20-run Submission Gate, judge-visible evidence.
- [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md) — authoritative current maturity and gate status.
- [docs/CLOUD_RUNTIME_MATRIX.md](docs/CLOUD_RUNTIME_MATRIX.md) — canonical GCP/Firebase production configuration.
- [docs/adr/](docs/adr/README.md) — architecture decision log. Every PR names the ADR it tracks.
# Trigger deployment
