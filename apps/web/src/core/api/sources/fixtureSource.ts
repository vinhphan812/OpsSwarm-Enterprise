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
