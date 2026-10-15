# API

Python FastAPI boundary for the web client. This is a demo scaffold for Weekend Demand Surge and does not constitute a production-ready system. By default it serves an in-process Live Twin seeded from the Day-0 fixture; only the guarded Executor writes it.

`POST /events` validates a normalized store event and keeps it in process memory. An `event_id` names one immutable payload. The same normalized event returns `200`. A different payload for that id returns `409` `event_id_conflict` and leaves the stored event in place. Acceptance does not change shelf or backroom quantity. Live writes stay behind the Decision Context Guard and the Executor.

`LIVE_TWIN_BACKEND` chooses what `GET /store` and `GET /inventory/{sku}` read. `memory` (the default) is an in-process Live Twin seeded from the fixture; `firestore` is the Firestore Live Twin (#6); `fixture` is the read-only day-0 fixture with no commit path. The routes and response models are the same for all three. This app does not close foundation gate #10.

`POST /simulations/{id}/approve` is the only route that changes the Live Twin (ADR 0016). It finds the planner's Decision for the simulation, runs the Decision Context Guard on fresh reads, issues a signed single-use authorization, and lets the guarded Executor commit exactly those actions with the versions the guard saw. Only `ALLOW` commits. The response carries the guard result with its per-gate checks.

The browser does not write to any external database in this demo mode. With the default backend this app does not connect to production APIs, Firestore, or LLM providers, and it does not publish events to production.

ADR: `docs/adr/0003-serve-store-reads-through-the-api.md`

## Endpoints

| Method | Path | Success | Failure |
| --- | --- | --- | --- |
| GET | `/health` | `200` with `status` `ok` or `degraded` | The process remains up for liveness probes even when store fixtures or dependencies fail |
| GET | `/ready` | `200` readiness status (`ready: true`) | `503` `store_unavailable` when store fixture is not loaded |
| GET | `/store` | `200` typed store view | `503` `store_unavailable` |
| GET | `/inventory/{sku}` | `200` one product | `404` `sku_not_found`, `503` `store_unavailable` |
| POST | `/events` | `201` first accept, `200` identical duplicate | `409` `event_id_conflict`, `404` `sku_not_found` or `store_not_found`, `422` `validation_error`, `503` `store_unavailable` |
| POST | `/simulations/{id}/approve` | `200` with the guard `verdict`; `ALLOW` means committed | `404` `simulation_not_found`, `503` `simulations_unavailable`, `commit_unavailable` or `decisions_unavailable` |
| POST | `/simulations/{id}/reject` | `200`, status `rejected`; Live is not touched | `404` `simulation_not_found`, `503` `simulations_unavailable` |

### Observable Health & Degradation Semantics (`/health` & `/ready`)
- **`/health` (Liveness probe):** Returns `200` with `status="ok"` when the store is loaded and downstream analytics integrations (anomalies, revenue, promotions repositories) execute successfully without raising exceptions. Returns `status="degraded"` **only** when the store fixture is not loaded OR when an analytics repository call actually raises an exception (e.g., database connection loss or GCP unreachable). Empty analytics datasets (e.g., zero anomalies for today) are valid operational states and return `ok`, not degraded.
- **`/ready` (Readiness probe):** Returns `200` with `ready=true` when the service is ready to accept traffic (`store.loaded == True`). Returns `503` with code `store_unavailable` when the store fixture is unavailable, signaling orchestrators/load balancers to drain traffic.

`GET /store` for the committed fixture returns `store-001`, `context_version` `store-001:v1`, and product `P001` on shelf `A01` / slot `A01-S01` with 3 facings, 8 on shelf, and 42 in the backroom. Product `version` is the fixture version as an integer (`1`). Ids are case-sensitive.

### Error Boundary & Failure-Safe Behavior
Errors adhere to a stable, non-sensitive JSON envelope and **never** echo raw request bodies or internal traceback paths:

```json
{"error": {"code": "sku_not_found", "message": "SKU 'P017' is not in store store-001."}}
```

- **Validation Errors (`HTTP 422`):** Include `error.details`, a structured list of `{field, message}` pairs detailing validation failures.
- **Client & Server Errors:** Return precise error codes (`sku_not_found`, `store_unavailable`, `event_id_conflict`, `validation_error`) ensuring predictable failure handling across UI and client SDK boundaries.

## Run locally

Python 3.11 or newer. From the repository root:

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m retailtwin_api
```

The server listens on `127.0.0.1:8000`. No GCP credentials are required.

Copy the repository `.env.example` to `.env` only when you need to override a setting. Do not commit `.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | Reported by `/health` |
| `API_HOST` | `127.0.0.1` | Bind address |
| `API_PORT` | `8000` | Bind port |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Browser origins allowed to call the API |
| `STORE_ID` | `store-001` | Store this process serves |
| `STORE_FIXTURE_PATH` | `data/schemas/store-state.example.json` | Day-0 read model |
| `LOG_LEVEL` | `INFO` | Log level |
| `LIVE_TWIN_BACKEND` | `memory` | `memory`, `firestore` or `fixture` (read-only, no commits) |
| `AUTONOMY_ENABLED` | `false` | A new `sale.completed` on `POST /events` starts an investigation with the configured LLM provider (ADR 0023) |
| `RETAILTWIN_COMMIT_SIGNING_KEY` | per-process random key outside production | HMAC key for commit authorizations; required in production |
| `RETAILTWIN_COMMIT_TOKEN_TTL_SECONDS` | `30` | Commit authorization lifetime |
| `RETAILTWIN_DCG_FRESHNESS_SECONDS` | `120` | Oldest context the guard accepts |
| `RETAILTWIN_DCG_MAX_FACINGS` | `12` | Facings limit per slot |
| `RETAILTWIN_DCG_MAX_ACTIONS` | `5` | More actions need a person |
| `RETAILTWIN_DCG_MAX_REPLENISH_UNITS` | `200` | A larger replenishment needs a person |
| `RETAILTWIN_REPLAN_MAX_REFRESHES` | `1` | Stale-context refreshes before re-plan stops |
| `LLM_PROVIDER` | `fake` | `fake`, `openai_compatible`, or `vertex_gemini` |
| `LLM_MODEL` | `fake-test` | Model name passed to the selected provider |
| `LLM_TIMEOUT_SECONDS` | `30` | Provider request timeout |
| `LLM_BASE_URL` | unset | OpenAI-compatible base URL. No default host |
| `LLM_API_KEY` | unset | OpenAI-compatible credential only. Vertex does not read it |
| `GOOGLE_CLOUD_PROJECT` | unset | Vertex project. Production must be `retailtwin-ai-511002` |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex region |

Accepted events log `event_id`, `correlation_id`, and `store_id` in process memory only. This demo scaffold does not publish events, connect to Firestore, or interact with BigQuery. Canonical event backbone implementation is out-of-scope for this demo.
// trigger

## Gemini inventory read

ADR 0021. `read_inventory` asks the injected provider for one `get_inventory` call and returns the typed Live Twin document. A missing SKU is `not_found`. Model prose is not inventory. The API process does not construct a provider, and this does not pass foundation gate #10 or gates G02–G06.

CI uses `FakeLlmProvider`. A live call is opt-in. Use Application Default Credentials for `retailtwin-ai-511002` (`gcloud auth application-default login`, then `gcloud auth application-default set-quota-project retailtwin-ai-511002`). Do not create a service-account key and do not set an API key. From this directory:

```bash
RETAILTWIN_VERTEX_LIVE=1 .venv/bin/python -m pytest tests/test_vertex_inventory_live.py -q
```

The test reads `store-001` / `P001` with `gemini-2.5-flash` in `us-central1`, then asks for one SKU that is not in the store. It does not write Firestore. Do not set `RETAILTWIN_VERTEX_LIVE` in CI.
