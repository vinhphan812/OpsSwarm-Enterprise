# 0003. Serve store reads through the API

Date: 2026-10-07

## Status

Accepted

## Context

Issue #8 needs a typed application boundary before the web client, later tools, or cloud data can share one contract. `docs/ARCHITECTURE.md` already says the frontend cannot bypass the backend guard or executor, and that live writes are not a general-purpose public API. `docs/DOMAIN_AND_DATA_MODEL.md` requires APIs to present one coherent typed view of Store → Zone → Shelf → Slot → Product, and it fixes the minimum store-event shape.

Firestore, Pub/Sub, and the control-loop contracts are still open. This service cannot pretend to be the Live Twin, and it cannot invent a second mutation path. The committed day-0 fixture is `data/schemas/store-state.example.json`: store `store-001`, version `v1`, product `P001` on shelf `A01` / slot `A01-S01`.

Two alternatives were set aside. Letting the browser read Firestore directly would couple the client to storage and skip this boundary. Applying a `sale.completed` event to shelf quantity inside this process would mutate operational state without the Decision Context Guard or the Executor.

## Decision

`apps/api` is the only application boundary the web client calls. The day-0 routes are `GET /health`, `GET /store`, `GET /inventory/{sku}`, and `POST /events`.

`GET /store` and `GET /inventory/{sku}` adapt the committed fixture into a typed view. `context_version` is `{store_id}:{version}` (for the fixture, `store-001:v1`). Each product carries that fixture version as an integer. The response includes only fields the fixture actually contains, plus `store_id` and `version`. It does not invent price, demand, or stockout figures.

`POST /events` accepts one normalized store event, validates it, and keeps it in process memory. The same `event_id` returns the first stored event and does not replace it. An event for an unknown SKU or a different store is rejected. Acceptance does not change inventory, publish to Pub/Sub, or call the Executor.

Failures use one JSON envelope: `{"error": {"code", "message", "details"?}}`. Unknown SKUs and unknown stores return 404. Invalid bodies return 422 and do not echo the submitted payload. A fixture that cannot be loaded returns 503 from the read and event routes. `GET /health` stays available and reports `degraded` in that case.

Configuration comes from environment variables. The process starts without GCP credentials. CORS allows only the configured web origins.

## Consequences

- The web client can show store and inventory data, and an API failure, without a direct database connection. The 3D scene from the store shell stays in place. `StoreStatus` sits in the Agent Activity column.
- `open_store` is the only read adapter. Issue #6 replaces that function with Firestore and keeps `GET /health`, `GET /store`, `GET /inventory/{sku}`, and `POST /events`. Issue #7 can publish accepted events.
- This record does not close foundation gate #10. Firestore, Pub/Sub, Gemini, and Cloud Run remain open.
- In-memory events disappear when the process stops. A duplicate `event_id` is idempotent only inside one process.
- Later live actions still enter through the Decision Context Guard and the Executor. This record does not add `POST /actions/submit` or `POST /guard/validate`.
- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/57
- Issue: https://github.com/vinhphan812/retailtwin-ai/issues/8
- Supersedes:
- Superseded by:
