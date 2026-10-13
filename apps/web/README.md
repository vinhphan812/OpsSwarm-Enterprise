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

> **Source policy.** Every build reads `apps/api` by default: the Live Twin (`GET /store`), `GET /health`, `GET /inventory/{sku}`, and the Revenue and Promotions routes. Only a development build swaps in a local twin or demo data, and only under `?twin=` (see *Twin sources*). `?twin=demo` calls no API at all. A failed API read never falls back to demo data. Routes `apps/api` does not serve yet (`/revenue`, `/promotions`, anomalies, checkouts; `TODO(BE)`) leave their panel empty.

## What is on screen

`/` is `TwinPage`. Any other path shows `NotFoundPage`.

- **3D view** (`StoreScene`): the store room, its fixtures, and the stock that twin state puts on them.
- **Overlays on the 3D view**:
  - `LensSwitcher` (top left): Operations, Revenue, or Promotions. Picking a lens opens the side panel on it. Revenue and Promotions read routes `apps/api` does not serve yet (`TODO(BE)`), so they show their empty report until it does.
  - `ViewModeSwitch` (top left, next to the lenses): **Live** or **Simulation**. Simulation can be picked only while a simulation is open (`twin.store.simulation`), and the view goes back to Live when it closes. A newly opened run raises a toast once ("New proposal: <id>", none if the Simulation view is already on), and a pulsing violet dot stays on Simulation until that run has been looked at. See *Live and Simulation views* below.
  - `SimulationBanner`: in the Simulation view, a violet frame around the 3D view (`--color-simulation`) and a label under the switches: SIMULATION, "Proposed store, not executed", the run id and status, the Live version it started from, and a warning once Live has moved on since.
  - `CameraHelp` (bottom left): lists the camera gestures.
  - `TwinStatusOverlay`: a spinner while the first state loads, then a small banner for problems (load failed, connection lost), with a retry button. The store always stays on screen: with empty shelves until a state arrives, then the last state. Errors also show as a toast.
  - `EntityInspector`: the details card of the selected entity, bottom left:
    - a product (`ProductInspector`): its twin figures, and its open anomalies (kind, severity, since when), noting one read from an older twin state than the one shown. **Details** opens `ProductDetailsDialog`;
    - a gondola or display equipment (`FixtureInspector`): products, slots used, units on the shelf and in the backroom, low and out-of-stock counts, and each product with its stock state. All from twin state (`fixtureStock`). A SKU in the list selects that product, and its info button opens its details dialog;
    - a checkout (`CheckoutInspector`): status, cashier, shift start, and today's revenue, transactions, average basket, items scanned, queue, and last sale, then **View payments**, which opens `PaymentsDialog`: today's sales at that lane, newest first, with totals, filtered by payment method or a search. Clicking a sale opens its receipt under it (SKU, quantity, unit price, line total); a SKU there selects the product in the 3D view and closes the dialog. `apps/api` serves no checkout data yet (`TODO(BE)`): `useCheckoutSummary` and `useCheckoutTransactions` return nothing, so the card says the figures are not available and has no payments button. The proposed shapes are `CheckoutSummary`, `CheckoutTransaction`, and `CheckoutLine` (`types/checkout.type.ts`).
  - `ProductDetailsDialog`: one product in a centered dialog: stock tiles (units on the shelf against facings with a fill bar, backroom, facings, version), its open anomalies marked by severity, and the promotions it is in (`usePromotions`). **Show in the store** selects it. Clicking one of its promotions selects the product and opens the Promotions lens on that promotion (`focusPromotion`): the lens drops a status filter that hides it, scrolls to its card, and flashes it for `PROMOTION_FLASH_MS`.
  - `TwinIssuesNotice`: products the scene left out, with the reason for each.
- **Agent Activity panel**: a side panel with a fixed width of 440px (`PANEL_WIDTH`). You can close it and open it again, and the open state is saved per browser. Each lens shows different content:
  - **Operations**: `StoreStatus` and the agent activity timeline from `run.store`. A SKU in the timeline selects that product, so the scene lights it up and flies the camera to it. `StoreStatus` shows product, low, and out-of-stock totals, then the first products one per line (out and low stock first). Clicking a line selects that product in the 3D view, and so does a SKU lookup that finds one. **Show all** opens `ProductsDialog`: every product with shelf, slot, facings, stock, and version, filtered by stock state or a search; clicking a row selects the product and closes the dialog. Given a client, `StoreStatus` reads `GET /health` once, shows the live store that the scene already polls (it does not call `GET /store` itself), and looks up `GET /inventory/{sku}`. The app gives it none for now (`TODO(BE)`): no health line, and the lookup reads the live store.
  - **Revenue**: metric tiles, a revenue chart, category share, and the best and worst SKUs (`useRevenue`). A SKU row selects that product.
  - **Promotions**: promotion cards by status (`usePromotions`). Each card lists its products as the twin has them now (slot, units on the shelf against facings, stock state); a product selects itself, and one the twin lacks shows as not in the store.
  - Opening either lens reads its route from `apps/api`. See *Revenue and promotions* below.

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
  - 3 checkouts, `CK01`–`CK03`, with lane barriers `BR01`–`BR07`. Each checkout has a lane light on a pole at its belt end: green while the lane is open, amber while paused, dark while closed. The status comes from `useCheckoutSummary`, like the checkout card, so every light is dark until `apps/api` serves checkouts (`TODO(BE)`).
  - 3 glass-door coolers (`GDC`) and 3 open chillers (`OC`) on the right wall.
  - 3 produce racks (`PR`) and a tiered display of wooden crates (`CW`) along the glass wall. The crates are decor: they hold no stock.
  - Plastic backstock crates (`CP`), also decor.
- **Slots**: every display surface of a fixture is split into slots, named `<fixtureId>-S01`, `-S02`, and so on (`slotsFor`). Checkouts, barriers, and crates have no slots, so a product put on one is reported as an unknown shelf.
- **Stock**: `Stock` draws every product in the store as a few instanced meshes. It draws one item per unit of `shelf_quantity`, front row first, up to what the facings hold. Items keep their natural width; one taller than the deck's clear height is drawn lower (`fitItem`). A slot holds `slotCapacity` facings at that width (`stock/capacity.ts`: 5 on a gondola, 2 in a glass-door cooler, 3 in an open chiller, 7 on a produce rack); the layout is the capacity source until the API serves `max_facings` (#92). More facings than that are an overflow, never a valid state: only the capacity is drawn, `SlotMarksLayer` outlines the slot in red, the product card flags it, and `TwinIssuesNotice` lists it (`facingsOverCapacity`). The count still follows twin state. Gondolas, coolers, and chillers show boxes. Produce racks show heaps of fruit. Twin state has no product looks, so each product's color and height come from its id (`stock/catalog.ts`).
- **Selection**: fixtures show no labels; the pointer turns into a hand over a selectable one. Clicking an item selects its product: its items glow (`Stock` draws them again in the `--color-selection` theme color, read by `themeColor`) and its card opens. Clicking a gondola or equipment with a card (rack, cooler, chiller, checkout) selects it, lights up its parts (`useSelectionGlow`), and opens its card; a click on one of its own items still selects the product. A press that moves more than `CLICK_SLOP_PX` is a camera drag and selects nothing. Opening `/?product=P001` selects that product on load. Clicking empty space clears the selection.
- **Anomalies**: every product with an open anomaly in `anomaly.store` gets a see-through halo around its items (`Stock`'s `AnomalyMesh`), selected or not, in its worst severity's color (`--color-anomaly-high|medium|low` theme tokens: red, orange, yellow). The halo pulses at `ANOMALY_PULSE_HZ`, and holds still under reduced motion. It sits outside the selection glow, so a selected product with an anomaly shows both. Only products in the twin state are drawn, so an anomaly on a SKU the twin lacks shows nothing, and an empty slot (a stockout) has no items to put a halo on. `anomaly.store` takes `setAll` (a `GET /anomalies` response), `raise` (an anomaly event; same `anomaly_id` replaces), and `resolve`. The contract is `Anomaly` and `AnomaliesResponse` in `types/anomaly.type.ts`, the FE's proposal. `apps/api` serves no anomalies yet (`TODO(BE)`), so only `?twin=demo` and tests fill the store.
- **Camera** (`CameraControls`):
  - Left drag orbits around the point under the cursor (`useOrbitAroundPointer`). That point is clamped to the zoom range, so a click never moves the camera.
  - Right drag (or two fingers) pans inside the store bounds.
  - The wheel zooms toward the cursor.
  - On every resize, `useFitCamera` fits the whole store into the canvas and limits zoom-out to 1.4× that distance.
  - On every new selection, `useFocusSelection` flies the camera to it (`scene/camera/focus.ts`): a product's slot from the side its stock faces, a little above, at the minimum zoom; a piece of equipment centered and fitted, seen from its front (into the room); a gondola the same, from the side the camera is on. The camera always stays inside the walls, and rises (up to `FOCUS_MAX_ELEVATION`) until no other fixture blocks its line of sight, so a slot across a 1.3 m aisle is seen over the next gondola. With the side panel open, the target lands in the middle of the part of the canvas the panel leaves visible (a focal offset, `panelOffset`). Once per selection, so twin updates never move the camera; a `?product=` selection is focused when the twin arrives. The flight is slower than a wheel step (`FOCUS_SMOOTH_TIME`) and instant under reduced motion.
- **Shadows**: the shadow map is redrawn only when stock changes or a wall hides or shows (`StaticShadows`), not on every frame of an orbit.

## Data flow

```text
TwinSource ──connectTwin──▶ parseStoreState ──▶ twin.store.live ──sceneOf──▶ StoreScene
                                  │                                  │
                                  └──── issues ─────────┬────────────┘
                                                        ▼
                                          TwinIssuesNotice, EntityInspector
```

1. `TwinPage` picks a `TwinSource` (`pickSource`) and passes it to `useTwinSource`. By default this is `apiSource`, which reads `GET /store` from `apps/api`.
2. `connectTwin` loads `snapshot()`, then follows `subscribe()`. `apiSource` has no push channel yet, so it polls `GET /store` every 5 s (`TWIN_POLL_MS`). It does not poll while the tab is hidden. Each failed read doubles the wait, up to 60 s (`TWIN_POLL_MAX_MS`), and a good read brings it back to 5 s. An outage is reported once. The next readable state ends it, and the stale banner goes away.
3. Each payload is checked by `parseStoreState` against the `GET /store` contract (`StoreResponse` in `types/twin.type.ts`, matching `apps/api`):
   - If the payload is not a store response, the first load fails. After the first state, the feed is marked stale instead.
   - A broken product is left out and reported as an issue. The rest of the store is still drawn.
4. A state is kept only when its `context_version` is newer than the last one, so a late snapshot or a replayed update never rolls the scene back.
5. `sceneOf` maps the live state onto the static layout (docs/adr/0007). Shelf, slot, facings, and stock come from state. A product is left out and reported if its shelf is unknown, its slot is not on that shelf, or its slot is already taken. A product with more facings than its slot holds is drawn up to the capacity and reported as `facingsOverCapacity`.

A product's entity id is its `sku`.

### Live and Simulation views

`twin.store` keeps `live` and `simulation` apart, and nothing copies one into the other. `simulation` is a `Simulation` (`types/simulation.type.ts`): the run id, the Live `base_context_version` it started from, its status, its actions (`move_product`, `change_facings`, `replenish_shelf`), and the proposed `state`. That shape is the FE's proposal for `GET /simulations/{simulation_id}`, which `apps/api` does not serve yet (`TODO(BE)`, #26).

- `activeState(twin, viewMode)` (`useActiveState`) is the state on screen: the proposal in the Simulation view, Live otherwise, and Live whenever no simulation is open. The scene (`TwinStoreContents`), the camera focus, the product and fixture cards, the details dialog, and `TwinIssuesNotice` read it. Store status, Revenue, and Promotions keep reading Live.
- Anomalies describe Live, so the Simulation view shows no halos and no anomaly lists (`useShownAnomalies`).
- A commit never touches `live` from the UI. Live changes only when the live feed brings a newer `context_version`. The simulation is then closed, and the view goes back to Live.
- With apps/api, `simulationSource` (`core/api/sources/simulationSource.ts`, through `useSimulationSource`) fills `simulation`: it reads `GET /simulations?status=open`, then `GET /simulations/{simulation_id}` for the first pending or evaluated run, checks it with `parseSimulation`, and polls like `apiSource` (every 5 s, backing off to 60 s while reads fail). A read of the same run that is not newer is dropped, a failed read keeps the last run without a toast, and once no run is open `simulation` goes back to null. `apps/api` serves neither route yet (`TODO(BE)`), so until it does no simulation opens and the Simulation switch stays off. Under a `?twin=` dev twin there is no simulation source; the console and the demo fixture fill it instead.

### Accepting or rejecting a proposal

While the Simulation view shows an **evaluated** run, the banner offers **Accept** and **Reject**. They are the only writes the web app makes, and they only *ask*: the browser never writes Live state (docs/DOMAIN_AND_DATA_MODEL.md §186). Accept hands the proposal to the Decision Context Guard, and only on `ALLOW` does the Executor apply it.

```text
Accept ─▶ POST /simulations/{simulation_id}/approve ─▶ DCG ─┬─ ALLOW ─▶ Executor ─▶ Live ─▶ GET /store ─▶ scene
                                                            ├─ REFRESH_REQUIRED ─▶ toast: needs a new simulation
                                                            ├─ DENY ─▶ toast with reason_code
                                                            └─ HUMAN_REVIEW ─▶ toast: needs another review
Reject ─▶ POST /simulations/{simulation_id}/reject ─▶ run closed, Live unchanged
```

**Domain** (FE proposal, `TODO(BE)`; apps/api serves neither route yet):

| Name | Where | What |
| --- | --- | --- |
| `REVIEW_DECISION` | `enums/simulation.enum.ts` | `approve` / `reject`; also the last path segment of the route |
| `GUARD_VERDICT` | `enums/simulation.enum.ts` | `ALLOW`, `DENY`, `REFRESH_REQUIRED`, `HUMAN_REVIEW` (`DCGVerdict`, contracts/TECHNICAL_SPEC.md §7) |
| `ReviewRequest` | `types/simulation.type.ts` | request body: `base_context_version` (the Live version the proposal was built on) and `proposal_context_version` (`simulation.state.context_version`), so the backend can refuse a review of something that has changed since |
| `ReviewResult` | `types/simulation.type.ts` | `simulation_id`, `decision`, `status` after the review (`committed` for an approval, `rejected` for a rejection, or still `evaluated` when the review was refused), `verdict` (a `DCGVerdict` on an approval, null on a rejection), `reason_code`, `live_context_version` (after an executed commit). `parseReviewResult` refuses any other combination |
| `REVIEW_REASON` | `enums/simulation.enum.ts` | `reason_code` of a refused review: `live_moved` (Live is no longer at `base_context_version`; approvals only) and `proposal_changed` (the run's proposal was replaced since it was reviewed; both decisions) |
| `client.reviewSimulation(id, decision, request)` | `core/api/client.ts` | `POST /simulations/{simulation_id}/approve\|reject`, answer checked by `parseReviewResult` |
| `SimulationReviewer` | `core/twin/simulationReview.ts` | `(simulation, decision) => Promise<ReviewResult>`: `createApiReviewer` for apps/api, `createMemoryReviewer` (`core/twin/memorySimulation.ts`) for `?twin=memory\|demo` |

**Behaviour** (`useSimulationReview`, `hooks/simulationReview.hook.ts`):

- `pickSimulationReviewer` (`core/twin/devSources.ts`) picks apps/api by default, the memory twin under `?twin=memory|demo`, and none under the other dev twins, which open no simulation.
- The buttons show only for an `evaluated` run and only when there is a reviewer. Both are disabled while a review is on its way, so a run is never reviewed twice at once.
- The answer is shown as a toast. Committed and rejected runs leave the buttons hidden with *Reviewed, waiting for Live*, until the simulation feed closes the run and the view goes back to Live. A refused approval or rejection keeps the buttons, so the run can be reviewed again later; a rejection refused with `proposal_changed` says *was not rejected*. A review is of one proposal (`simulation_id` and `state.context_version`), so a proposal replaced under the same run id offers the buttons again. A failed request (apps/api does not serve the route yet) shows *Could not send the review*.
- Nothing on screen changes from the answer itself. Live changes only when `GET /store` brings a newer `context_version`, and the run closes only when `GET /simulations?status=open` stops listing it.
- Under `?twin=memory|demo`, `createMemoryReviewer` stands in for the backend. Both decisions are refused with `proposal_changed` once the open run's proposal has been replaced (Reject with `verdict: null`, Accept with `REFRESH_REQUIRED`), and the run stays open. Otherwise Reject drops the run, even if Live has moved on, and Accept runs a minimal guard (`REFRESH_REQUIRED` with `reason_code: "live_moved"` once Live has moved on since `base_context_version`, `ALLOW` otherwise) and writes the proposal to the twin, which pushes it to the live feed. `twin.commit()` in the console goes through the same path. With a candidate selected (#27), both review the candidate on screen: its `state.context_version` is the proposal version, so selecting another candidate refuses a review of the first with `proposal_changed`.

**What apps/api has to serve** for this to work without `?twin=`: the two routes above with the `ReviewRequest` body and the `ReviewResult` answer. An approval needs both versions to be current, and a rejection only `proposal_context_version` (it never writes Live); a refused review answers `evaluated` with a `REVIEW_REASON`; an approval returns the guard's verdict; and a committed or rejected run drops out of `GET /simulations?status=open`.

### State diff

`diffStates(prev, next)` (`core/twin/stateDiff.ts`) says what changed between two twin states, per SKU and sorted by SKU: `moved` (from and to `shelf_id`/`slot_id`), `facings` (before and after), `quantity` (signed `shelfDelta` and `backroomDelta`), and `added` / `removed` SKUs. A product can be in several lists at once, such as a move that also changes its facings. States of different stores give `EMPTY_DIFF`. The diff is always read from **state**: simulation actions only label a change (#92), so a cue can never show something the state does not.

The diff has two uses, both read through `useRecentChanges()` (`hooks/recentChanges.hook.ts`) for the view on screen:

- **Live → Live.** `setLive` diffs each new live state against the one before and keeps the result, its time, and the Live state before it (`before`) as `twin.store.liveChange`. The first state is a load, not a change. A state that changes nothing (a poll with no move, facings, or quantity change) leaves the last change as it was.
- **Live → Simulation.** In the Simulation view, the hook diffs the current Live state against the proposal, timed from when the view was opened (`ui.store.viewChangedAt`) or the proposal last changed (`twin.store.simulationChangedAt`). It is computed when needed and never stored. Because it is against the current Live state and not the simulation's `base_context_version`, Live changes made since the simulation opened show up in it too.

For `CHANGE_CUE_MS` (4 s) the hook returns `{ diff, at, before }`, where `before` is the state the diff was taken from (the previous Live state, or Live for a proposal), so a cue can still draw what was there, such as a moved product's old facings at its source slot. After that it returns null, so the cues of #23, #24, #25 and #27 fade by themselves. A facings change (#24) glows on its slot (`SlotMarksLayer`, fading over the cue; still under reduced motion) and the product card shows `Facings 2 → 5` (`useFacingsChange`), in the Live and Simulation views. `CHANGE_CUE_MS` is shorter than `TWIN_POLL_MS`, so the next poll never replaces a cue that is still showing.

**Move cue (#23).** `moveCueOf` (`scene/entities/stock/moveCue.ts`) turns the recent change's `moved` into what `Stock` draws: the product's items travel from the source slot to the destination over `MOVE_TWEEN_MS` (0.9 s), hopping on a low arc (`MOVE_ARC_HEIGHT`) so they clear the shelf edge. A thin outline (`--color-change`) of where the product stood (`before`) stays at the source, and both slots light up. The marks fade in over `MOVE_MARK_IN_MS`; while the items travel the light hands over from the source slot to the destination (`MOVE_SLOT_HANDOFF`); when they land the destination flashes (`MOVE_ARRIVAL_FLASH`) and everything fades out over `MOVE_MARK_OUT_MS` (`markLevels`, `marksShown`). The tween only shifts where the items are drawn; its last frame, and any tween cut short, puts them back where the state puts them. With reduced motion there is no tween, arc, fade or flash; the outline and lights hold still for `MOVE_TWEEN_MS`. The product card and details dialog say "Moved from B02-S20" while the change is recent (`useMovedFrom`). Leaving a proposal plays it back the same way: back in Live from the Simulation view, or after a proposal on screen is rejected or discarded (`twin.store.leftProposal`), the hook cues Live against that proposal, so P007 travels from B02-S22 back to B02-S20 with its outline and slot lights. An approval leaves no such cue, since Live then changes through its feed. Try it with `twin.simulate({ type: "move_product", sku: "P001", from_slot: "A01-S01", to_slot: "A02-S02" })` and the Simulation view, or `twin.patch("P001", { shelf_id: "A02", slot_id: "A02-S02" })` in Live.

**Replenishment cue (#25).** A recent stock change shows on the product card and in the details dialog as `Shelf +12` / `Backroom -12` (`useQuantityChange`), and a shelf gain glows on its slot like a facings change (`SlotMarksLayer`); the figures always come from state. A change that is not a matching backroom → shelf transfer is flagged as an `inconsistentTransfer` product issue (`transferIssues`): the shelf gained units or the backroom lost some, and the two deltas do not cancel out. A sale (shelf down only) and a delivery (backroom up only) are not flagged. The flag is read from the change that led to the state on screen, so it stays until the next Live change, or for as long as the Simulation view shows the proposal against Live; the product stays drawn. Shelf units past what the facings hold are not drawn, and the card and dialog say `+N not shown` (`unitsDrawn`, `useUnitsNotShown`). Try it with `twin.patch("P001", { shelf_quantity: 12, backroom_quantity: 38 })` for a matching transfer (P001 starts at 8 / 42), then `twin.patch("P001", { shelf_quantity: 20 })` for the flag.

### Revenue and promotions

| Lens | Route | Response type | Client |
| --- | --- | --- | --- |
| Revenue | `GET /revenue?period=today\|7d\|30d` | `RevenueSummary` (`types/revenue.type.ts`) | `client.revenue(period)` |
| Promotions | `GET /promotions` | `PromotionsSummary` (`types/promotion.type.ts`) | `client.promotions()` |

`useRevenue` and `usePromotions` read the route the first time a lens (or a period, or a product's details dialog for promotions) opens, never on page load, then cache the result, so switching lenses does not call the API again. The lens shows the empty report (`emptyRevenue`, `emptyPromotions`) until the read lands. A failed read shows one toast and is retried the next time the lens opens.

`apps/api` does not serve either route yet (`TODO(BE)` on the types), so outside `?twin=demo` the read fails with one toast and the lens keeps its empty report. Under `?twin=demo`, `commerceClient` reads the demo report instead.

### Twin sources

`apiSource` (the Live Twin from `GET /store` on `VITE_API_BASE_URL`) is the default, and the only source of a production build. In development, `?twin=` swaps in a local source:

| `?twin=` | Source |
| --- | --- |
| (none) | `apiSource`: `GET /store`, polled every 5 s, backing off to 60 s while it fails |
| `fixture` | `fixtureSource`: empty shelves, no live updates |
| `memory` | empty shelves in memory, editable from the browser console: `twin.add()` adds the API fixture's P001, then `twin.patch("P001", { facings: 5 })`, `twin.patch("P001", null)`, `twin.state()` |
| `demo` | the same editable twin, stocked with the demo store, plus demo data where `apps/api` serves none yet: checkout figures, payments and receipts, Revenue and Promotions reports, anomalies (`twin.anomalies()`; `twin.raise("P001")` raises an anomaly event on a product, `twin.resolve("P001")` closes it), and an open simulation. All of it lives in `fixtures/demo/` and is marked **Demo data** where it shows; see *Demo data* below |
| `slow` | the snapshot takes 4 s |

Under `memory` and `demo`, the console also drives simulations (`core/twin/memorySimulation.ts`), standing in for the simulation API and the guarded commit: `twin.simulate()` opens a simulation of the demo actions on the current state (or of the actions passed in, such as `twin.simulate({ type: "change_facings", sku: "P001", facings: 5 })`), `twin.commit()` writes the proposal to the twin, which pushes it to the live feed, or refuses with `REFRESH_REQUIRED` once Live has moved on, and `twin.discard()` drops it. `twin.candidate("cand-b")` shows one of the open run's candidates in the Simulation view and `twin.candidate(null)` the run's own proposal, until #39's panel calls `selectCandidate`. The banner's **Accept** and **Reject** do the same through `createMemoryReviewer`.
| `offline` | the snapshot fails after 1.2 s |
| `flaky` | the live feed drops 3 s after loading |


### Demo data

`?twin=demo` (development builds only, `isDemoMode`) turns on made-up data for the demo, all in `fixtures/demo/`:

| File | What | Read by |
| --- | --- | --- |
| `store.ts` | a product on every kind of fixture that holds stock, some out of stock or low | the twin source |
| `checkouts.ts` | three lanes (open, paused, closed) and today's sales with receipt lines, from a fixed price list | `useCheckoutSummary`, `useCheckoutTransactions` |
| `commerce.ts` | Revenue for every window (today adds up the checkout sales) and Promotions in every status | `useRevenue`, `usePromotions` through `demoClient` |
| `simulation.ts` | `sim-demo-001`: restock P003, one more facing for P004, P007 moved from B02-S20 to B02-S22, and the well-stocked P008 (C01-S21 → A02-S22) and P005 (A03-S22 → B01-S22) moved to another gondola, so a move shows a full facing travel | `twin.store.simulation` on load; `twin.simulate()` in the console |
| `candidates.ts` | three candidates of `sim-demo-001` (#27): `cand-a` the whole demo plan, `cand-b` restock P003 and re-face P004, `cand-c` the three moves; each with its own proposal version and no KPI values | `twin.store.candidates` on load; `twin.candidate("cand-b")` in the console |
| `anomalies.ts` | open anomalies that agree with the demo store's stock: stockouts and low stock where the shelf says so, and sales drops on full shelves, so a halo shows at every severity | `anomaly.store` on load; `twin.anomalies()`, `twin.raise()` in the console |

The figures agree with each other: a lane's card adds up its sales, each sale its receipt lines, and today's revenue the lanes. Everything else still reads `apps/api`. Without `?twin=demo`, and in tests, none of it is used. The whole demo is one commit, so it can be reverted on its own.
## Source layout

```text
src/
  main.tsx                  entry point: loads i18n, mounts <App /> in StrictMode
  api-env.d.ts              VITE_API_BASE_URL typing
  app/
    App.tsx                 routes: / → TwinPage, * → NotFoundPage
    Providers.tsx           router, HeroUI (en-US locale), toasts, reduced motion
    App.css                 Tailwind entry, @theme palette, page layout
    hero.ts                 HeroUI dark theme, loaded from App.css with @plugin
  pages/                    TwinPage, NotFoundPage
  components/
    layout/                 AgentActivityPanel, LensSwitcher, CameraHelp, lens.ts
    twin/                   TwinStatusOverlay, TwinIssuesNotice, EntityInspector and its cards
    status/                 StoreStatus (API health, store, and SKU lookup)
    revenue/                RevenuePanel, RevenueChart, CategoryShare, SkuList
    promotions/             PromotionsPanel, PromotionCard
    commerce/               shared panel parts: MetricTile, AnimatedNumber, Segmented
    common/                 ListDialog: a fixed-size dialog of a filtered table that alone scrolls
    icons.tsx               line icons
  core/
    api/
      client.ts             REST client for /health, /store, /inventory/{sku}, /revenue, /promotions,
                            /simulations (read, and the approve / reject review)
      validate.ts           parseStoreState, parseSimulation, parseReviewResult: contract checks
      version.ts            context_version parsing and ordering
      sources/              TwinSource interface; apiSource (GET /store), fixture and in-memory sources
    twin/
      twinConnection.ts     connectTwin: snapshot + updates, validated and in version order
      twinIssues.ts         all products left out of the scene; inspectProduct
      devSources.ts         pickSource: apiSource, or a ?twin= source while developing
      memorySimulation.ts   simulations on the in-memory twin: open, review (guarded commit or reject), discard
      simulationReview.ts   SimulationReviewer: Accept / Reject through POST /simulations/{id}/approve|reject
      stateDiff.ts          diffStates: what changed between two twin states, per SKU
    notify.ts               toast helpers and errorMessage
    utils/                  groupBy, padId, seeded PRNG, number/money/date formatters
  hooks/                    twinSource, networkStatus, productParam, twinIssues, storeStatus,
                            commerce, hover, fitCamera, orbitPoint, simulationReview, recentChanges
  state/                    Zustand stores, read-side copies only
    twin.store.ts           live state, last live change, open simulation, issues, status, stale flag,
                            retry; activeState
    run.store.ts            agent activity (deduplicated by id) and the current loop stage
    ui.store.ts             selected entity, lens, live/simulation view mode
    panel.store.ts          side panel open state, saved in localStorage
  scene/
    StoreScene.tsx          Canvas, lights, environment, camera controls, StoreContents
    layout.ts               storeLayout, toSceneStore / sceneOf: twin state onto the layout
    camera/cameraFrame.ts   fit-the-store camera distance for an aspect ratio
    utils/transform.ts      fixture matrices, footprints, tilt
    entities/               Floor, Walls, Glazing, Exterior, Shelf, Slot, SlotProducts, Product,
                            HitBox, entity.ts (name + userData), woodTexture.ts
      equipment/            Checkout, Barrier, GlassDoorCooler, OpenChiller, ProduceRack, Crate,
                            Equipment (dispatch by kind), parts.tsx (shared box parts and materials)
      stock/                Stock (instanced items), catalog.ts (looks), surfaces.ts (display surfaces)
  fixtures/
    storeFixture.ts         the static layout: gondolas and equipment, no products
    commerceFixture.ts      empty revenue and promotions reports, shown until a read lands
  constants/                <area>.constant.ts: camera, dimensions, scene, twin, app, i18n, commerce
  enums/                    <area>.enum.ts: as-const value sets and their types
  types/                    <domain>.type.ts: twin, simulation, api, agent, anomaly, revenue, promotion, scene
  i18n/                     i18next setup, English only; locales/en.ts (also the source of the key types)
  test/                     Vitest suites, mirroring the src/ folders
```

## Rules

- **Read only.** A `TwinSource` never writes. The Zustand stores are copies of backend state, not the source of truth. The one request that writes is a proposal review (Accept / Reject), and it only asks the backend; see *Accepting or rejecting a proposal*.
- **Made-up data is labeled.** What the 3D view and the panels show must come from the twin and `apps/api`, never from state the UI made up (issue #22). The one exception is the demo data in `fixtures/demo/`, shown only under `?twin=demo` where `apps/api` serves none yet (checkout figures, payments, Revenue and Promotions reports): it carries a **Demo data** label (`DemoBadge`), and new made-up figures take it too. The UI has no controls that make up state; anomalies to try the highlight on come from the demo data, or from `twin.raise()` in the console.
- **Layout is static** until the twin serves geometry (docs/adr/0007). Positions live in `fixtures/storeFixture.ts`. Sizes in meters live in `constants/dimensions.constant.ts`, not inline in meshes.
- **Naming**:
  - Shared data types go in `types/<domain>.type.ts`.
  - Value sets go in `enums/<area>.enum.ts`, written as `as const` objects plus a type.
  - Fixed values go in `constants/<area>.constant.ts`.
  - Hooks are named `<name>.hook.ts`. Zustand stores are named `<name>.store.ts`.
  - Component props, and types derived from code, stay next to that code.
- **Imports** use `@/`. `scene/` does not import from `components/`. The panels and the scene talk through `state/`.
- **Text** goes through i18n (`t()`), in `locales/en.ts`. The app is English only. Numbers, dates, and money use `format` (`en-US`, USD).
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
| `apiBinding.test.tsx` | issue #4 over HTTP: P001 from the committed seed, a seed change redraws it, a reload rebuilds the same state, reads only |
| `twinBinding.test.tsx` | P001 follows a live twin change, and a broken record is dropped and reported |
| `core/api/sources/apiSource.test.ts` | snapshot and polling of `GET /store`, backoff after failed reads, unsubscribe |
| `core/api/sources/fixtureSource.test.ts` | the fixture state is valid; `PRODUCT_FIELDS` matches the pydantic models in `apps/api` |
| `core/api/validate.test.ts` | contract check: bad envelopes throw, bad products are left out with a reason; a review answer needs a known decision, status and (for an approval) guard verdict |
| `core/api/version.test.ts` | context version parsing and ordering |
| `core/api/client.test.ts` | REST client paths, including revenue, promotions, simulations and the approve / reject POST with its body, and error envelopes |
| `core/twin/twinConnection.test.ts` | load states, out-of-order snapshot and updates, feed drop and recovery, unreadable payloads |
| `core/twin/stateDiff.test.ts` | issue #91: moves (across and within a shelf), facings, signed quantity deltas, added and removed SKUs, several changes at once; equal states, product order, and other stores give no diff |
| `hooks/recentChanges.test.tsx` | issue #91: a Live change is cued and fades after `CHANGE_CUE_MS`; the Simulation view cues the proposal against Live and leaves Live alone |
| `scene/layout.test.ts` | placement from state; unknown shelf, wrong slot, and taken slot are reported |
| `scene/StoreScene.test.tsx` | scene objects are named with their entity ids |
| `core/twin/fixtureStock.test.ts` | a fixture's stock totals and states follow the twin |
| `components/twin/EntityInspector.test.tsx` | product, shelf, and checkout cards; a SKU in a shelf's list selects it; Close clears the selection |
| `scene/selection.test.tsx` | product, shelf, and checkout selection glow and clear again; a fixture click leaves its own items to the product; drags select nothing |
| `scene/anomaly.test.tsx` | issue #22: with P001 selected, an anomaly event puts a halo around exactly its items and keeps the selection glow, and resolving removes it; the halo takes the worst severity's color; the card shows the anomaly next to P001's twin figures and flags an older state |
| `scene/entities/stock/Stock.test.ts` | stock is deterministic, follows facings and quantity, and fills the front row first |
| `scene/camera/focus.test.ts` | the camera faces a product's slot from its stock's side (far side, equipment too), sees wall equipment from inside the room and a gondola from the camera's side, and never ends up behind a wall |
| `scene/camera/cameraFrame.test.ts` | every shelf corner stays in frame on desktop and on a 390px canvas |
| `state/*.test.ts` | twin store (issue #91: the first state records no change, a change is kept with its time, an unchanged state keeps it) and run store (the anomaly store is in `scene/anomaly.test.tsx`); issue #26: a simulation never changes Live, and the state on screen follows the view mode |
| `state/candidates.test.tsx` | issue #27: the selected candidate drives the Simulation view and falls back to the run's proposal; switching never changes Live and replays the cues; the selection survives new candidates and is dropped with its run; every changed slot is outlined, a move's source too; the banner counts the changes and focuses one; the memory reviewer commits the candidate on screen only |
| `simulationBinding.test.tsx` | issue #26: the scene draws Live, then the proposal in the Simulation view (without halos), then Live again; the demo simulation places every product |
| `components/layout/ViewModeSwitch.test.tsx` | issue #26: Simulation cannot be picked with no simulation open; a new run raises one toast and a dot until it is looked at; the banner names the run and its base, warns once Live moves on, and the view goes back to Live when the simulation closes |
| `core/api/sources/simulationSource.test.ts` | issue #26: `parseSimulation` checks the run like `GET /store`; the source reads the open run, drops stale reads, keeps the last run on a failure and backs off, and goes to null once the run closes |
| `core/twin/memorySimulation.test.ts` | issue #26: opening and discarding leave Live alone; a commit reaches Live only through the live feed, and is refused once Live has moved on; the memory reviewer answers ALLOW / REFRESH_REQUIRED / rejected and refuses a run that is no longer open |
| `components/twin/SimulationReview.test.tsx` | Accept and Reject show only for an evaluated run with a reviewer, send the run and leave the twin state to the feeds, are disabled while a review is on its way, toast every guard verdict and a failed request; on the memory twin, Accept commits through the live feed or is refused once Live has moved on |
| `components/twin/ProductDetails.test.tsx` | the details dialog opens from the product card and a shelf's list, shows the product's twin figures, its anomalies, and only the promotions it is in; **Show in the store** selects it, and a promotion opens the Promotions lens on it; the lens shows every status again, flashes that card, and clears the request |
| `components/commerce/productLinks.test.tsx` | Revenue SKU rows and promotion products select their product; a promotion SKU the twin lacks cannot be selected |
| `components/**`, `app/App.test.tsx` | StoreStatus (a lookup selects the product it finds), AgentActivityPanel (a timeline SKU selects its product), LensSwitcher (revenue and promotions reads), routing |
| `fixtures/demo/*.test.ts*` | demo mode is on only under `?twin=demo`; the demo store, anomalies, checkouts, revenue, and promotions add up; the lenses read them in demo mode |
| `stockedState.test.ts` | the stocked test store (`stockedState.ts`) passes the contract and places every product; out-of-stock products draw no items |
| `fixtures/commerceFixture.test.ts`, `i18n/`, `core/utils/` | empty commerce reports, English messages and issue reasons, formatters and utils |

## Maturity

- Issue #4: the scene reads `GET /store` from `apps/api` and binds P001 by its SKU. Today the API serves the committed seed `data/schemas/store-state.example.json`. Issue #6 swaps that for Firestore behind the same route.
- To check #4 by hand:
  1. Run the API (`python -m retailtwin_api` in `apps/api`) and the web app (`npm run dev`). P001 shows on `A01-S01`.
  2. In the seed, change P001's `facings`, `shelf_quantity`, or `slot_id`, and bump `version` (for example to `v2`).
  3. Restart the API. Within 5 s the scene redraws P001. A page reload rebuilds the same state.
- With the API stopped, the page shows a toast and a small "Could not load" banner over the store with empty shelves. When the API comes back, the next poll loads the store.
- `StoreStatus` also calls the API (issue #8).
- Revenue and promotions read `GET /revenue` and `GET /promotions`, which `apps/api` does not serve yet (`TODO(BE)`). The lens switch shows them anyway; they stay empty until the routes exist.
- Issue #22: selection, highlight, details cards, the product details dialog, camera focus, and the anomaly halo are done on the FE. A product can be selected from the 3D view, a shelf's card, the Agent Activity timeline, a SKU lookup, Revenue's SKU lists, and a promotion's products. It stays open until `apps/api` serves anomalies (and their events) and checkout data. To check by hand: `npm run dev`, open `/?twin=demo`. P003, P004, P006, P007, P009, P010, and P012 carry demo anomalies and show a halo in their severity's color where the shelf has items (P003 and P010 are empty). Select one, and its card and **Details** list the anomaly. To raise one by hand, run `twin.raise("P001")` in the console; `twin.resolve("P001")` clears it.
- Issue #27: `twin.store` holds the open run's `candidates` and `selectedCandidateId`; the Simulation view (`shownSimulation`, `activeState`) shows the selected candidate's actions and state, else the run's own. While a proposal is on screen every slot it changes against Live is outlined in `--color-change` (`useProposalChanges`, `SlotMarksLayer`), a move's source slot included, and the banner lists the changed products (*N changes*); one click selects and focuses it. Switching candidates replays the move and facings cues. #39's panel selects candidates and shows KPIs; #93 reads them from `GET /simulations/{id}/candidates`. To check by hand: `npm run dev`, open `/?twin=demo`, switch to Simulation, and run `twin.candidate("cand-b")`, then `"cand-c"`.
- Issue #58 stays open until a GitHub Actions CI gate runs `npm ci`, the build, and the tests.
// trigger CI re-check
