# API

Python FastAPI boundary for the web client. This is a demo scaffold for Weekend Demand Surge and does not constitute a production-ready system. It uses an in-memory fixture for Day-0 reads and cannot write to Firestore or any external provider.

## Current status

The API implementation is **not yet merged on `main`**. PR #57 is the current implementation work for issue #8. Until that PR is reconciled and merged, this directory on `main` is documentation/target scope only.

The browser does not write to any external database in this demo mode. This app does not connect to production APIs, Firestore, or LLM providers. As a demo scaffold, it does not support action submission, complex guard validation, or production-bound event publishing.

ADR: `docs/adr/0003-serve-store-reads-through-the-api.md`

PR #57 currently uses the committed store fixture as a typed read model so frontend/API integration can be tested before Firestore issue #6 lands. That fixture is not the Live Twin.

## Target responsibility

The API is the browser-facing application boundary. The frontend must not write Firestore or other Live Twin storage directly.

Later action flow is:

```text
Frontend / Agent
      ↓
submit action/decision
      ↓
Decision Context Guard
      ↓
commit authorization
      ↓
Executor
      ↓
Live Twin
```

Endpoints such as action submission/guard validation are target contracts and must not be documented as available until their implementing issues land.

## Safety invariant

**No general-purpose API endpoint may bypass Simulation-before-Live, DCG, authorization, or Executor for a live mutation.**

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

Accepted events log `event_id`, `correlation_id`, and `store_id` in process memory only. This demo scaffold does not publish events, connect to Firestore, or interact with BigQuery. Canonical event backbone implementation is out-of-scope for this demo.
// trigger
