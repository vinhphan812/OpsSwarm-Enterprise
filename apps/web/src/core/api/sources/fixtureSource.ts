import { mockStoreState } from "@/mocks";
import type { StoreResponse } from "@/core/api/types";
import type { TwinSource } from "./TwinSource";

/** Store state from the mock JSON. Dev and test only, never Live Twin truth. */
export function fixtureStoreState(): StoreResponse {
  // A copy, so a caller that edits its state cannot change the next snapshot.
  return structuredClone(mockStoreState);
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
