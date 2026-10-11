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
