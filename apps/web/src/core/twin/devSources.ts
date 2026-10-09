import { createApiSource } from "@/core/api/sources/apiSource";
import { fixtureSource, fixtureStoreState } from "@/core/api/sources/fixtureSource";
import { createMemoryTwin, patchProduct } from "@/core/api/sources/memorySource";
import type { TwinSource } from "@/core/api/sources/TwinSource";
import type { ProductInventory } from "@/types/twin.type";
import { FIXTURE_P001 } from "@/constants/twin.constant";

/** A twin that cannot be reached: loads for a while, then fails. */
const unreachableSource: TwinSource = {
  snapshot: () =>
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error("Twin API unreachable (simulated)")), 1200);
    }),
  subscribe: () => () => {},
};

/** A slow twin: the snapshot takes a few seconds, so the loading screen stays up. */
const slowSource: TwinSource = {
  snapshot: () => new Promise((resolve) => setTimeout(() => resolve(fixtureStoreState()), 4000)),
  subscribe: () => () => {},
};

/** A twin whose live feed drops a few seconds after loading; the last state stays on screen. */
const flakySource: TwinSource = {
  snapshot: () => Promise.resolve(fixtureStoreState()),
  subscribe: (_onState, onError) => {
    const timer = setTimeout(() => onError?.(new Error("Live feed closed (simulated)")), 3000);
    return () => clearTimeout(timer);
  },
};

/** Simulated twins for checking the status screens; development builds only. */
const DEV_SOURCES: Record<string, TwinSource> = {
  fixture: fixtureSource,
  offline: unreachableSource,
  slow: slowSource,
  flaky: flakySource,
};

/**
 * An editable twin for checking live updates by hand, driven from the browser console.
 * It starts with empty shelves: `twin.add()` puts the API fixture's P001 on A01-S01,
 * `twin.patch("P001", { facings: 5 })` changes it, `twin.patch("P001", null)` removes it.
 */
function memoryTwinSource(): TwinSource {
  const twin = createMemoryTwin(fixtureStoreState());
  Object.assign(window, {
    twin: {
      add: (product: ProductInventory = FIXTURE_P001) =>
        twin.update((state) => ({ ...state, products: [...state.products, product] })).context_version,
      patch: (sku: string, patch: Parameters<typeof patchProduct>[2]) =>
        twin.update((state) => patchProduct(state, sku, patch)).context_version,
      state: twin.current,
    },
  });
  return twin.source;
}

/**
 * The Live Twin from apps/api. While developing, `?twin=fixture|memory|offline|slow|flaky`
 * swaps in a local twin instead.
 */
export function pickSource(): TwinSource {
  if (import.meta.env.DEV) {
    const mode = new URLSearchParams(window.location.search).get("twin") ?? "";
    if (mode === "memory") return memoryTwinSource();
    if (mode in DEV_SOURCES) return DEV_SOURCES[mode];
  }
  return createApiSource();
}
