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

This page is the API status view. It does not render the 3D scene.

`src/status/StoreStatus.tsx` loads `GET /health` and `GET /store`, and looks up `GET /inventory/{sku}`. The client lives in `src/api`. It does not post events and it does not change inventory.

Set `VITE_API_BASE_URL` to the API origin. The default is `http://127.0.0.1:8000`. Vite reads `apps/web/.env.local` (do not commit it). Start the API before the page if you want live data. If the API is down, the page shows "The API is unreachable." and the SKU form stays on screen.

Node `>=20.17` is required. This app stays on React 18 and Vite 6 so it builds on that Node line.

```bash
cd apps/web
npm install
npm test
npm run dev
npm run build
```

`npm run dev` serves the page at http://localhost:5173.
