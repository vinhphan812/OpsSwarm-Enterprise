# Web App

React + TypeScript frontend for RetailTwin. It draws store-001 in 3D from Live Twin state, and shows the Agent Activity panel next to it.

The web app only reads. It never writes to live store state.

## Run

Node `>=20.17` is required. The app stays on React 18, React Three Fiber 8, and Vite 6 so it builds on that Node line.

```bash
cd apps/web
npm ci          # package-lock.json is tracked
npm test        # vitest, node environment
npm run dev     # http://localhost:5173
npm run build   # tsc --noEmit, then vite build
```

Set `VITE_API_BASE_URL` to the API origin. The default is `http://127.0.0.1:8000`. Put it in `apps/web/.env.local`, and do not commit that file.

## What is on screen

`/` is `TwinPage`. Any other path shows `NotFoundPage`.

- **3D view** (`StoreScene`): the store room, its fixtures, and the stock that twin state puts on them.
- **Overlays on the 3D view**:
  - `LanguageToggle` (top left): Vietnamese or English. Vietnamese is the default, and the choice is saved in `localStorage`.
  - `LensSwitcher` (top): Operations, Revenue, or Promotions. Picking a lens opens the side panel on it.
  - `CameraHelp` (bottom left): lists the camera gestures.
  - `TwinStatusOverlay`: shows loading and errors. Before the first state, it covers the room. After that, it shows a small banner, and the last state stays on screen.
  - `ProductInspector`: the twin figures of the selected product.
  - `TwinIssuesNotice`: products the scene left out, with the reason for each.
- **Agent Activity panel**: a side panel with a fixed width of 380px (`PANEL_WIDTH`). You can close it and open it again, and the open state is saved per browser. Each lens shows different content:
  - **Operations**: `StoreStatus` and the agent activity timeline from `run.store`. `StoreStatus` reads `GET /health` once, shows the live store that the scene already polls (it does not call `GET /store` itself), and looks up `GET /inventory/{sku}`.
  - **Revenue**: metric tiles, a revenue chart, category share, and the best and worst SKUs. All figures are 0 until `GET /sales/summary` exists (`useRevenue`).
  - **Promotions**: promotion cards by status. The list is empty until `GET /promotions` exists (`usePromotions`).

Errors and network changes show as HeroUI toasts (`core/notify.ts`). When the browser comes back online, `useNetworkStatus` reconnects if the last load failed or the live feed dropped.

## The scene

- **Room**: a 14 m × 11 m floor with a procedural oak plank texture. The texture is drawn on a canvas with a seeded PRNG, so it looks the same on every load. In node tests there is no canvas, so the floor is a flat color there.
- **Walls**: a U-shaped shell with the front (+Z) left open:
  - The back wall has a wood slat panel and a sliding glass door.
  - The left wall is a glass curtain wall.
  - A wall hides itself while the camera is outside it.
  - The lawn and sky outside are an `Exterior` plane plus the background color and fog.
- **Fixtures**: listed in `fixtures/storeFixture.ts`:
  - 9 double-sided gondolas, `A01`–`C03`.
  - 3 checkouts, `CK01`–`CK03`, with lane barriers `BR01`–`BR07`.
  - 3 glass-door coolers (`GDC`) and 3 open chillers (`OC`) on the right wall.
  - 3 produce racks (`PR`) and a tiered display of wooden crates (`CW`) along the glass wall.
  - Plastic backstock crates (`CP`).
- **Slots**: every display surface of a fixture is split into slots, named `<fixtureId>-S01`, `-S02`, and so on (`slotsFor`). Checkouts, barriers, and plastic crates have no slots.
- **Stock**: `Stock` draws every product in the store as a few instanced meshes. It draws one item per unit of `shelf_quantity`, front row first, up to what the facings hold. Gondolas, coolers, and chillers show boxes. Produce racks and wooden crates show heaps of fruit. Twin state has no product looks, so each product's color and height come from its id (`stock/catalog.ts`).
- **Hover and selection**: hovering a fixture shows a label with its category and id. Clicking an item selects its product and opens `ProductInspector`. Opening `/?product=P001` selects that product on load. Clicking empty space clears the selection.
- **Camera** (`CameraControls`):
  - Left drag orbits around the point under the cursor (`useOrbitAroundPointer`). That point is clamped to the zoom range, so a click never moves the camera.
  - Right drag (or two fingers) pans inside the store bounds.
  - The wheel zooms toward the cursor.
  - On every resize, `useFitCamera` fits the whole store into the canvas and limits zoom-out to 1.4× that distance.
- **Shadows**: the shadow map is redrawn only when stock changes or a wall hides or shows (`StaticShadows`), not on every frame of an orbit.

## Data flow

```text
TwinSource ──connectTwin──▶ parseStoreState ──▶ twin.store.live ──sceneOf──▶ StoreScene
                                  │                                  │
                                  └──── issues ─────────┬────────────┘
                                                        ▼
                                          TwinIssuesNotice, ProductInspector
```

1. `TwinPage` picks a `TwinSource` (`pickSource`) and passes it to `useTwinSource`. By default this is `apiSource`, which reads `GET /store` from `apps/api`.
2. `connectTwin` loads `snapshot()`, then follows `subscribe()`. `apiSource` has no push channel yet, so it polls `GET /store` every 5 s (`TWIN_POLL_MS`). It does not poll while the tab is hidden. Each failed read doubles the wait, up to 60 s (`TWIN_POLL_MAX_MS`), and a good read brings it back to 5 s. An outage is reported once. The next readable state ends it, and the stale banner goes away.
3. Each payload is checked by `parseStoreState` against the `GET /store` contract (`StoreResponse` in `types/twin.type.ts`, matching `apps/api`):
   - If the payload is not a store response, the first load fails. After the first state, the feed is marked stale instead.
   - A broken product is left out and reported as an issue. The rest of the store is still drawn.
4. A state is kept only when its `context_version` is newer than the last one, so a late snapshot or a replayed update never rolls the scene back.
5. `sceneOf` maps the live state onto the static layout (docs/adr/0006). Shelf, slot, facings, and stock come from state. A product is left out and reported if its shelf is unknown, its slot is not on that shelf, or its slot is already taken.

A product's entity id is its `sku`.

### Twin sources

Every build reads `apiSource` by default: the Live Twin from `GET /store` on `VITE_API_BASE_URL`. In development, `?twin=` swaps in a local source:

| `?twin=` | Source |
| --- | --- |
| (none) | `apiSource`: `GET /store`, polled every 5 s, backing off to 60 s while it fails |
| `fixture` | `fixtureSource`: empty shelves, no live updates |
| `memory` | empty shelves in memory, editable from the browser console: `twin.add()` adds the API fixture's P001, then `twin.patch("P001", { facings: 5 })`, `twin.patch("P001", null)`, `twin.state()` |
| `slow` | the snapshot takes 4 s |
| `offline` | the snapshot fails after 1.2 s |
| `flaky` | the live feed drops 3 s after loading |

## Source layout

```text
src/
  main.tsx                  entry point: loads i18n, mounts <App /> in StrictMode
  api-env.d.ts              VITE_API_BASE_URL typing
  app/
    App.tsx                 routes: / → TwinPage, * → NotFoundPage
    Providers.tsx           router, HeroUI (locale follows the language), toasts, reduced motion
    App.css                 Tailwind entry, @theme palette, page layout
    hero.ts                 HeroUI dark theme, loaded from App.css with @plugin
  pages/                    TwinPage, NotFoundPage
  components/
    layout/                 AgentActivityPanel, LensSwitcher, LanguageToggle, CameraHelp, lens.ts
    twin/                   TwinStatusOverlay, TwinIssuesNotice, ProductInspector
    status/                 StoreStatus (API health, store, and SKU lookup)
    revenue/                RevenuePanel, RevenueChart, CategoryShare, SkuList
    promotions/             PromotionsPanel, PromotionCard
    commerce/               shared panel parts: MetricTile, AnimatedNumber, Segmented
    icons.tsx               line icons
  core/
    api/
      client.ts             REST client for /health, /store, /inventory/{sku}; ApiError
      validate.ts           parseStoreState: the GET /store contract check
      version.ts            context_version parsing and ordering
      sources/              TwinSource interface; apiSource (GET /store), fixture and in-memory sources
    twin/
      twinConnection.ts     connectTwin: snapshot + updates, validated and in version order
      twinIssues.ts         all products left out of the scene; inspectProduct
      devSources.ts         pickSource: apiSource, or a ?twin= source while developing
    notify.ts               toast helpers and errorMessage
    utils/                  groupBy, padId, seeded PRNG, number/money/date formatters
  hooks/                    twinSource, networkStatus, productParam, twinIssues, storeStatus,
                            commerce, format, hover, fitCamera, orbitPoint
  state/                    Zustand stores, read-side copies only
    twin.store.ts           live state, issues, status, stale flag, retry
    run.store.ts            agent activity (deduplicated by id) and the current loop stage
    ui.store.ts             selected entity, lens, live/simulation view mode
    panel.store.ts          side panel open state, saved in localStorage
  scene/
    StoreScene.tsx          Canvas, lights, environment, camera controls, StoreContents
    layout.ts               storeLayout, toSceneStore / sceneOf: twin state onto the layout
    camera/cameraFrame.ts   fit-the-store camera distance for an aspect ratio
    utils/transform.ts      fixture matrices, footprints, tilt
    entities/               Floor, Walls, Glazing, Exterior, Shelf, Slot, SlotProducts, Product,
                            HoverLabel, entity.ts (name + userData), woodTexture.ts
      equipment/            Checkout, Barrier, GlassDoorCooler, OpenChiller, ProduceRack, Crate,
                            Equipment (dispatch by kind), parts.tsx (shared box parts and materials)
      stock/                Stock (instanced items), catalog.ts (looks), surfaces.ts (display surfaces)
  fixtures/
    storeFixture.ts         the static layout: gondolas and equipment, no products
    commerceFixture.ts      empty revenue and promotions in the future API shape
  constants/                <area>.constant.ts: camera, dimensions, scene, twin, app, i18n, commerce
  enums/                    <area>.enum.ts: as-const value sets and their types
  types/                    <domain>.type.ts: twin, api, agent, revenue, promotion, scene
  i18n/                     i18next setup; locales/vi.ts (source of the key types) and locales/en.ts
  test/                     Vitest suites, mirroring the src/ folders
```

## Rules

- **Read only.** A `TwinSource` never writes. The Zustand stores are copies of backend state, not the source of truth.
- **Layout is static** until the twin serves geometry (docs/adr/0006). Positions live in `fixtures/storeFixture.ts`. Sizes in meters live in `constants/dimensions.constant.ts`, not inline in meshes.
- **Naming**:
  - Shared data types go in `types/<domain>.type.ts`.
  - Value sets go in `enums/<area>.enum.ts`, written as `as const` objects plus a type.
  - Fixed values go in `constants/<area>.constant.ts`.
  - Hooks are named `<name>.hook.ts`. Zustand stores are named `<name>.store.ts`.
  - Component props, and types derived from code, stay next to that code.
- **Imports** use `@/`. `scene/` does not import from `components/`. The panels and the scene talk through `state/`.
- **Text** goes through i18n. A new key goes into `locales/vi.ts` first. `en.ts` must have the same keys and placeholders, and a test checks this.
- **Tests** live in `src/test/`, in the same folder as the file they test. For example, `scene/layout.ts` is tested by `test/scene/layout.test.ts`.

### Scene conventions

- Y is up, units are meters, and the floor top is at `y = 0`.
- Store, shelf, slot, product, and equipment objects set `name` and `userData.entityId` to the domain id, and `userData.entityType` to the entity type (`entityProps`).
- A fixture faces its local +Z. `rotationY` is one of the `FACING` turns.
- Slot ids are `<fixtureId>-S<nn>`. This matches `slot_id` in `docs/DOMAIN_AND_DATA_MODEL.md`.

## Tests

Vitest runs in the `node` environment. Scene tests use `@react-three/test-renderer`, and `vitest.setup.ts` sets `IS_REACT_ACT_ENVIRONMENT`. Paths below are relative to `src/test/`.

| Test | Covers |
| --- | --- |
| `twinBinding.test.tsx` | P001 follows a live twin change, and a broken record is dropped and reported |
| `core/api/sources/apiSource.test.ts` | snapshot and polling of `GET /store`, backoff after failed reads, unsubscribe |
| `core/api/sources/fixtureSource.test.ts` | the fixture state is valid; `PRODUCT_FIELDS` matches the pydantic models in `apps/api` |
| `core/api/validate.test.ts` | contract check: bad envelopes throw, bad products are left out with a reason |
| `core/api/version.test.ts` | context version parsing and ordering |
| `core/api/client.test.ts` | REST client paths and error envelopes |
| `core/twin/twinConnection.test.ts` | load states, out-of-order snapshot and updates, feed drop and recovery, unreadable payloads |
| `scene/layout.test.ts` | placement from state; unknown shelf, wrong slot, and taken slot are reported |
| `scene/StoreScene.test.tsx` | scene objects are named with their entity ids |
| `scene/entities/stock/Stock.test.ts` | stock is deterministic, follows facings and quantity, and fills the front row first |
| `scene/camera/cameraFrame.test.ts` | every shelf corner stays in frame on desktop and on a 390px canvas |
| `state/*.test.ts` | twin store and run store |
| `components/**`, `app/App.test.tsx` | StoreStatus, AgentActivityPanel, LensSwitcher, routing |
| `fixtures/commerceFixture.test.ts`, `i18n/`, `core/utils/` | empty commerce reports, locale parity, formatters and utils |

## Maturity

- Issue #4: the scene reads `GET /store` from `apps/api` and binds P001 by its SKU. Today the API serves the committed seed `data/schemas/store-state.example.json`. Issue #6 swaps that for Firestore behind the same route.
- To check #4 by hand:
  1. Run the API (`python -m retailtwin_api` in `apps/api`) and the web app (`npm run dev`). P001 shows on `A01-S01`.
  2. In the seed, change P001's `facings`, `shelf_quantity`, or `slot_id`, and bump `version` (for example to `v2`).
  3. Restart the API. Within 5 s the scene redraws P001. A page reload rebuilds the same state.
- With the API stopped, the page shows the load error and a retry button. When the API comes back, the next poll loads the store.
- `StoreStatus` also calls the API (issue #8).
- Revenue and promotions are UI only, with empty data in the shape their future APIs will return.
- Issue #58 stays open until a GitHub Actions CI gate runs `npm ci`, the build, and the tests.
