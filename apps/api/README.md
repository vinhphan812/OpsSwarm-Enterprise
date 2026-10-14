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
| GET | `/health` | `200` with `status` `ok` or `degraded` | The process is up even when the fixture did not load |
| GET | `/store` | `200` typed store view | `503` `store_unavailable` |
| GET | `/inventory/{sku}` | `200` one product | `404` `sku_not_found`, `503` `store_unavailable` |
| POST | `/events` | `201` first accept, `200` identical duplicate | `409` `event_id_conflict`, `404` `sku_not_found` or `store_not_found`, `422` `validation_error`, `503` `store_unavailable` |
| POST | `/simulations/{id}/approve` | `200` with the guard `verdict`; `ALLOW` means committed | `404` `simulation_not_found`, `503` `simulations_unavailable`, `commit_unavailable` or `decisions_unavailable` |
| POST | `/simulations/{id}/reject` | `200`, status `rejected`; Live is not touched | `404` `simulation_not_found`, `503` `simulations_unavailable` |

`GET /store` for the committed fixture returns `store-001`, `context_version` `store-001:v1`, and product `P001` on shelf `A01` / slot `A01-S01` with 3 facings, 8 on shelf, and 42 in the backroom. Product `version` is the fixture version as an integer (`1`). Ids are case-sensitive.

Errors use one envelope and do not echo the request body:

```json
{"error": {"code": "sku_not_found", "message": "SKU 'P017' is not in store store-001."}}
```

Validation errors add `error.details`: a list of `{field, message}`.

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
| `RETAILTWIN_COMMIT_SIGNING_KEY` | per-process random key outside production | HMAC key for commit authorizations; required in production |
| `RETAILTWIN_COMMIT_TOKEN_TTL_SECONDS` | `30` | Commit authorization lifetime |
| `RETAILTWIN_DCG_FRESHNESS_SECONDS` | `120` | Oldest context the guard accepts |
| `RETAILTWIN_DCG_MAX_FACINGS` | `12` | Facings limit per slot |
| `RETAILTWIN_DCG_MAX_ACTIONS` | `5` | More actions need a person |
| `RETAILTWIN_DCG_MAX_REPLENISH_UNITS` | `200` | A larger replenishment needs a person |

Accepted events log `event_id`, `correlation_id`, and `store_id` in process memory only. This demo scaffold does not publish events, connect to Firestore, or interact with BigQuery. Canonical event backbone implementation is out-of-scope for this demo.
// trigger
