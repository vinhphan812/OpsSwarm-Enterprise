# API

Python FastAPI boundary for the web client. Day-0 reads come from the committed fixture at `data/schemas/store-state.example.json`. This process is not the Live Twin and it does not write Firestore.

`POST /events` validates a normalized store event and keeps it in process memory. An `event_id` names one immutable payload. The same normalized event returns `200`. A different payload for that id returns `409` `event_id_conflict` and leaves the stored event in place. Acceptance does not change shelf or backroom quantity. Live writes stay behind the Decision Context Guard and the Executor.

`open_store` in `retailtwin_api/store.py` is the read adapter. Issue #6 replaces that function. The routes and response models stay the same. This app does not close foundation gate #10.

The browser does not write Firestore. This app does not expose action submission or guard validation; those stay target contracts. No route bypasses Simulation-before-Live, the Decision Context Guard, authorization, or the Executor.

ADR: `docs/adr/0003-serve-store-reads-through-the-api.md`

## Endpoints

| Method | Path | Success | Failure |
| --- | --- | --- | --- |
| GET | `/health` | `200` with `status` `ok` or `degraded` | The process is up even when the fixture did not load |
| GET | `/store` | `200` typed store view | `503` `store_unavailable` |
| GET | `/inventory/{sku}` | `200` one product | `404` `sku_not_found`, `503` `store_unavailable` |
| POST | `/events` | `201` first accept, `200` identical duplicate | `409` `event_id_conflict`, `404` `sku_not_found` or `store_not_found`, `422` `validation_error`, `503` `store_unavailable` |

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

Accepted events log `event_id`, `correlation_id`, and `store_id`. The log is process memory only. This route does not publish. The store-events backbone is a separate command, documented in [infrastructure/gcp/store-events.md](../../infrastructure/gcp/store-events.md). That command claims the event id in Firestore and writes the derived BigQuery row. It does not make this process the Live Twin.
