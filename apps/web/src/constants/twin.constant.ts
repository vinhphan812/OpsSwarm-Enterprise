import type { ProductInventory } from "@/types/twin.type";
import apiFixture from "../../../../data/schemas/store-state.example.json";

/** P001 as `GET /store` serves it from the API's day-0 fixture. */
export const FIXTURE_P001: ProductInventory = { ...apiFixture.products[0], store_id: apiFixture.store_id, version: 1 };

/** How often the scene re-reads `GET /store` while apps/api has no push channel. */
export const TWIN_POLL_MS = 5000;
/** Longest wait between reads while the API keeps failing; each failure doubles the wait up to this. */
export const TWIN_POLL_MAX_MS = 60_000;
/**
 * How long a change cue (move, facings, replenishment) stays on screen. Shorter than
 * `TWIN_POLL_MS`, so the next poll never replaces a cue that is still showing.
 */
export const CHANGE_CUE_MS = 4000;
/** How long a moved product takes to travel from its source slot to its destination. Shorter than `CHANGE_CUE_MS`. */
export const MOVE_TWEEN_MS = 900;
/** How long a move's outline and slot lights take to fade in, and to fade out once the items land. */
export const MOVE_MARK_IN_MS = 150;
export const MOVE_MARK_OUT_MS = 600;
/**
 * In the Simulation view, how long a move's marks hold at full strength once the items land,
 * before they fade: the proposal is there to be looked at. `MOVE_TWEEN_MS` plus this plus
 * `MOVE_MARK_OUT_MS` stays within `CHANGE_CUE_MS`.
 */
export const MOVE_MARK_HOLD_SIMULATION_MS = 2000;
/** How long one item that a facings change or shelf gain adds takes to grow in. */
export const ARRIVAL_GROW_MS = 350;
/** The window over which a product's new items start growing, one after another. Together with `ARRIVAL_GROW_MS`, shorter than `CHANGE_CUE_MS`. */
export const ARRIVAL_SPREAD_MS = 500;
