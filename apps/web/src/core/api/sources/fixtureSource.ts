import { storeFixture } from "@/fixtures/storeFixture";
import type { StoreResponse } from "@/types/twin.type";
import type { TwinSource } from "./TwinSource";

/**
 * `GET /store` for the layout's store with empty shelves: the scene draws only the
 * shelves and equipment until a real source sends products. Dev and test only, never
 * Live Twin truth. A new object per call, so a caller that edits it cannot change the next.
 */
export function fixtureStoreState(): StoreResponse {
  const storeId = storeFixture.storeId;
  return { store_id: storeId, context_version: `${storeId}:v1`, version: "v1", products: [] };
}

/** A source whose state never changes after the snapshot. */
export const fixtureSource: TwinSource = {
  snapshot: () => Promise.resolve(fixtureStoreState()),
  subscribe: () => () => {},
};

/*
 * Dev-only sources for checking the status screens by hand. TwinPage picks one
 * with the `?twin=` query parameter.
 */

/** A twin that cannot be reached: loads for a while, then fails. */
export const unreachableSource: TwinSource = {
  snapshot: () =>
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error("Twin API unreachable (simulated)")), 1200);
    }),
  subscribe: () => () => {},
};

/** A slow twin: the snapshot takes a few seconds, so the loading screen stays up. */
export const slowSource: TwinSource = {
  snapshot: () => new Promise((resolve) => setTimeout(() => resolve(fixtureStoreState()), 4000)),
  subscribe: () => () => {},
};

/** A twin whose live feed drops a few seconds after loading; the last state stays on screen. */
export const flakySource: TwinSource = {
  snapshot: () => Promise.resolve(fixtureStoreState()),
  subscribe: (_onState, onError) => {
    const timer = setTimeout(() => onError?.(new Error("Live feed closed (simulated)")), 3000);
    return () => clearTimeout(timer);
  },
};
