import {
  fixtureSource,
  fixtureStoreState,
  flakySource,
  slowSource,
  unreachableSource,
} from "@/core/api/sources/fixtureSource";
import { createMemoryTwin, patchProduct } from "@/core/api/sources/memorySource";
import type { TwinSource } from "@/core/api/sources/TwinSource";
import type { ProductInventory } from "@/types/twin.type";
import { FIXTURE_P001 } from "@/constants/twin.constant";

/** Simulated twins for checking the status screens; development builds only. */
const DEV_SOURCES: Record<string, TwinSource> = {
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

/** `?twin=offline|slow|flaky|memory` swaps in a simulated twin while developing. */
export function pickSource(): TwinSource {
  if (!import.meta.env.DEV) return fixtureSource;
  const mode = new URLSearchParams(window.location.search).get("twin") ?? "";
  if (mode === "memory") return memoryTwinSource();
  return DEV_SOURCES[mode] ?? fixtureSource;
}
