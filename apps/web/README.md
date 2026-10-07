# Web App

React + TypeScript frontend.

Responsibilities:
- render the 3D store
- bind scene objects to Digital Twin state
- show Agent Activity, alerts, KPI comparison, and Current vs AI Proposal
- call the API for health, store, and inventory
- show an API failure without crashing
- never write directly to live store state

## API status

The 3D scene stays in the viewport. `StoreStatus` is mounted in the Agent Activity column. It loads `GET /health` and `GET /store`, and looks up `GET /inventory/{sku}`. The client lives in `src/api`. It does not post events and it does not change inventory.

Set `VITE_API_BASE_URL` to the API origin. The default is `http://127.0.0.1:8000`. Vite reads `apps/web/.env.local` (do not commit it). Start the API before the page if you want live data. If the API is down, the page shows "The API is unreachable." and the SKU form stays on screen.

Node `>=20.17` is required. This app stays on React 18 and Vite 6 so it builds on that Node line.
## Issue #3 scaffold

`src/scene` renders store-001 as colored primitives: a floor, shelves A01/A02/B01/B02, and products P001/P002. Layout numbers live in `src/scene/storeFixture.ts`. That fixture is view data. It is not Live Twin truth.

Each store, shelf, slot, and product object sets `name` and `userData.entityId` to the domain id. The scene is Y-up, in meters, with the floor top on `y = 0`.

Node `>=20.17` is required. This app stays on React 18 and React Three Fiber 8 so it builds on that Node line.

```bash
cd apps/web
npm ci
npm test
npm run dev
npm run build
```

`npm run dev` serves the store at http://localhost:5173.


## Current maturity and integration

The issue #3 scene on `main` is fixture-backed view data. It is not a Firestore or Live Twin implementation.

Issue #8 is implemented here. `StoreStatus` calls the FastAPI boundary for health, store, and inventory. Those reads use the committed fixture. They are not Live Twin truth. Issue #4 replaces the scene fixture with state from that boundary and keeps the domain entity IDs.

`apps/web/package-lock.json` is tracked. Install with `npm ci`. Issue #58 remains open until an executable GitHub Actions CI gate uses that lockfile and passes the build and tests.
