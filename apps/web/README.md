# Web App

React + TypeScript + React Three Fiber/Three.js frontend.

Responsibilities:
- render the 3D store
- bind scene objects to Digital Twin state
- show Agent Activity, alerts, KPI comparison, and Current vs AI Proposal
- never write directly to live store state

## Issue #3 scaffold

`src/scene` renders store-001 as colored primitives: a floor, shelves A01/A02/B01/B02, and products P001/P002. Layout numbers live in `src/scene/storeFixture.ts`. That fixture is view data. It is not Live Twin truth.

Each store, shelf, slot, and product object sets `name` and `userData.entityId` to the domain id. The scene is Y-up, in meters, with the floor top on `y = 0`.

Node `>=20.17` is required. This app stays on React 18 and React Three Fiber 8 so it builds on that Node line.

```bash
cd apps/web
npm install
npm test
npm run dev
npm run build
```

`npm run dev` serves the store at http://localhost:5173.
