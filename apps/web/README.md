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

## Current state

The app renders store-001 as a 3D room:

- **Floor**: a wood-plank slab. The plank texture is drawn on a canvas at runtime (`woodTexture.ts`) with a seeded PRNG, so it looks the same on every load. Unit tests run in node, where there is no canvas, so the floor falls back to a flat wood color there.
- **Walls**: a U-shaped shell. The back wall is at -Z and the side walls are at ±X. The front (+Z) is left open for the camera.
  - The back wall has a wood slat panel and a sliding glass door.
  - The left wall is a floor-to-lintel glass curtain wall.
  - A wall hides itself while the camera orbits outside it, so it never blocks the view inside.
- **Exterior**: a lawn plane seen through the glass. The sky is the scene background color plus fog.
- **Lighting**: hemisphere, ambient, and a warm shadow-casting sun from the left. Reflections come from drei `Lightformer`s, so no HDR file is downloaded.
- **Camera**: `OrbitControls` with pan off and a polar limit that stops the camera above the floor. On resize, `FrameCamera` fits the camera distance to the window aspect ratio so all shelves and checkouts stay in frame on phones too.
- **Shelves**: 8 gondolas (A01–A04, B01–B04) in two aisles at the back left. `arrangeShelves` builds the grid from a config (aisles, shelves per run, aisle width, runs along X or Z). The two runs of an aisle face each other, and neighbouring aisles stand back to back. It throws if a shelf would overlap another shelf, sit closer than 0.8 m to a wall, block the door, or enter the checkout zone. Each gondola has 4 decks × 3 slots, price strips and tags, and a header sign in its category color.
- **Products**: 96 essentials (`productCatalog.ts`): 8 categories × 4 lines × 3 pack sizes, drawn as low-poly packaging (bottle, carton, can, bag, box, cup, jar, jug, roll). `assignProductsToShelves` keeps one category per row. A category starts on a new row and spills to the next row, then the next shelf. With the default catalog each shelf holds one category, and each row holds one line in S/M/L. Every part of a product is one `instancedMesh` covering all its facings and the units behind them.
- **Checkouts**: two counters, CK01 and CK02, at the front right. Their positions are constants (`CHECKOUT_LANES`), not twin state, and shelves stay out of `CHECKOUT_ZONE`.
- **Customers**: `Customer.tsx` (low-poly shopper with a basket or cart) and five customers in the fixture exist, but rendering them in `StoreContents` is commented out for now.

Data flow:

```text
TwinSource ──connectTwin──▶ parseStoreState ──▶ twin.store.live ──sceneOf──▶ StoreScene
                                  │                                  │
                                  └──── issues ─────────┬────────────┘
                                                        ▼
                                          TwinIssuesNotice, ProductInspector
```

`TwinPage` passes a `TwinSource` to `useTwinSource`. The connection loads `snapshot()`, then follows `subscribe()` updates. A state is kept only when its `context_version` is newer than the last one, so a late snapshot or a replayed update never rolls the scene back. Every payload is checked by `parseStoreState` against the `GET /store` contract (`StoreResponse` in `src/api/types.ts`, matching `apps/api`): a payload that is not a store response fails the load (or marks the feed stale after the first state), and a broken product is left out and reported. A product's entity id is its `sku`.

`sceneOf` maps `live` onto the static layout (docs/adr/0005). Slot, facings, and stock come from state: the scene draws one item per unit of `shelf_quantity`, front row first, up to what the facings hold. A product whose shelf or slot is not in the layout, or whose slot is already taken, is left out and reported. Click an item on a shelf, or open `/?product=P001`, to see the product's figures.

The scene does not read the API yet: every build reads `src/mocks/store-001.state.json`, a `GET /store` response with no products, so only the shelves and equipment are drawn. `StoreStatus` in the Agent Activity column does read the API. Tests use `src/test/sampleState.ts`, the API fixture as `GET /store` serves it. In development, `?twin=` swaps the scene's source:

| `?twin=` | Source |
| --- | --- |
| (none) | the mock JSON (empty shelves), no live updates |
| `memory` | empty shelves in memory, editable from the console: `twin.add()` adds the API fixture's P001, `twin.patch("P001", { facings: 5 })`, `twin.patch("P001", null)` |
| `slow` | the snapshot takes 4 s |
| `offline` | the snapshot fails after 1.2 s |
| `flaky` | the live feed drops 3 s after loading |

## Source layout

```text
src/
  main.tsx                     entry point, mounts <App /> in StrictMode
  vite-env.d.ts
  app/
    App.tsx                    app shell, wires fixtureSource into the scene
    App.css                    page-level layout styles
    useTwinSource.ts           loads a TwinSource snapshot and updates into twin.store
  api/
    types.ts                   wire types from docs/DOMAIN_AND_DATA_MODEL.md
                               (StoreState, ProductState, ControlStage, GuardVerdict, ActivityEntry)
    sources/                   read-only twin state feeds
      TwinSource.ts            snapshot() + subscribe() interface
      fixtureSource.ts         StoreState built from the fixture, dev and test only
  state/                       Zustand stores, read-side copies of backend state
    twin.store.ts              Live and Simulation store state
    run.store.ts               Agent Activity entries (deduped by id) and current loop stage
    ui.store.ts                selected entity and LIVE/SIMULATION view mode
  scene/                       React Three Fiber store scene
    StoreScene.tsx             Canvas, lights, environment, controls; reads live state from twin.store
    scene.css                  label styles
    layout.ts                  storeLayout + toSceneStore: twin state onto the fixed layout
    types.ts                   scene input types (StoreFixture, ShelfFixture, SlotFixture, ProductFixture,
                               CheckoutFixture, CustomerFixture)
    camera/
      cameraFrame.ts           FOV, orbit target, fit-to-aspect distance math
    config/
      dimensions.ts            fixed sizes in meters (floor, walls, glazing, shelf, aisles, product shapes,
                               checkout lanes and zone, customer)
      categories.ts            product categories, header label and color per category
    placement/                 pure layout math, no React
      footprint.ts             floor rectangles: shelf/checkout/customer footprints, door zone, overlap tests
      shelfLayout.ts           arrangeShelves (aisle grid + validation), slotsFor, slotId
      assignProducts.ts        assignProductsToShelves: one category per row
      facings.ts               fitFacings, unitsDeep, shapeSize
    entities/
      entity.ts                entityProps: sets name and userData on domain objects
      Floor.tsx                floor slab with wood texture
      woodTexture.ts           procedural oak plank CanvasTexture
      Walls.tsx                wall shell, openings, slat panel, hide-when-behind
      Glazing.tsx              CurtainWall and SlidingDoor
      Exterior.tsx             lawn outside the store
      Shelf.tsx                gondola: plinth, back panel, decks, price strips and tags, header sign
      Slot.tsx                 positioned group for a slot
      Product.tsx              facings × units deep, one instancedMesh per part
      products/productParts.ts low-poly packaging per shape, shared geometries and materials
      Checkout.tsx             counter, belt, scanner, POS, card terminal, bagging area, lane sign
      Customer.tsx             low-poly shopper with optional basket or cart (not rendered yet)
  fixtures/
    productCatalog.ts          96 essentials: name, category, shape, pack scale, colors
    storeFixture.ts            default shelf grid, product placement, checkouts, customers;
                               dev and test data only, never used as Live Twin truth
```

Folders planned for later issues:

```text
src/
  api/client.ts, api/stream.ts   REST client and realtime stream for apps/api
  features/inspector/            selected entity details
  features/candidates/           candidate plans and KPI comparison
  features/guard/                Decision Context Guard result and version diff
  features/demo/                 demo scenario controls
  scene/overlays/                highlight, risk tint, simulation ghost
  scene/animations/              move, facings and replenish transitions
```

## Rules

- Tests live under `src/test/`, in the same folders as the file they test: `src/scene/layout.ts` is tested by `src/test/scene/layout.test.ts`. Tests import the code through `@/`.
- Zustand store files are named `<name>.store.ts`, for example `twin.store.ts`. Their tests are `<name>.store.test.ts`. This suffix is only for Zustand stores; other files keep their current names.
- A feature keeps its own `.css` file next to its component.
- `scene/` must not import from `features/`. Panels and the scene talk through `state/`.
- The web app only reads twin state. A `TwinSource` never writes, and the Zustand stores are copies, not the source of truth.
- Fixed sizes go in `scene/config/dimensions.ts`, not inline in meshes.
- Layout math lives in `scene/placement/` as pure functions with tests, not inside components.

## Scene conventions

- Y is up, units are meters, and the floor top sits on `y = 0`.
- Each store, shelf, slot, product, checkout, and customer object sets `name` and `userData.entityId` to the domain id, and `userData.entityType` to `"store" | "shelf" | "slot" | "product" | "checkout" | "customer"` (see `entityProps`).
- Shelf ids are `<aisle letter><nn>`. In each aisle the back run comes first, for example `A01`–`A02` then `A03`–`A04` on the opposite run.
- Slot ids are `<shelfId>-S<nn>`, numbered row by row from the bottom deck, left to right: `A01-S01`–`S03` is the bottom row and `A01-S12` is the top right. This matches `slot_id` in `docs/DOMAIN_AND_DATA_MODEL.md`.
- A shelf, checkout, or customer faces its local +Z. `rotationY` is a multiple of π/2.

## Tests

Vitest runs in the `node` environment. Scene tests use `@react-three/test-renderer`, and `vitest.setup.ts` sets `IS_REACT_ACT_ENVIRONMENT`.

Paths below are relative to `src/test/`.

| Test | Covers |
| --- | --- |
| `scene/StoreScene.test.tsx` | store, shelves, slots, products, and checkouts are named with their entity ids |
| `scene/layout.test.ts` | `toSceneStore` takes facings, slot, and category from twin state; unknown products fall back |
| `scene/placement/shelfLayout.test.ts` | shelves stay clear of walls, door, checkouts, and each other; runs are straight; bad configs throw |
| `scene/placement/assignProducts.test.ts` | one category per row, fresh row per category, every product gets a slot |
| `fixtures/storeFixture.test.ts` | every product fits under the next deck; checkouts and customers clear of shelves |
| `scene/camera/cameraFrame.test.ts` | every shelf and checkout corner stays in frame on desktop and on a 390px canvas |
| `state/twin.store.test.ts` | `setLive` replaces the live state |
| `state/run.store.test.ts` | activity append, latest stage, duplicate id ignored |

## Run

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
