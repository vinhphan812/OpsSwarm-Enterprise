import type { ProductInventory, StoreResponse } from "@/core/api/types";
import { contextRevision } from "@/core/api/version";
import type { TwinSource } from "./TwinSource";

/** A twin held in memory that pushes every change, like a live backend. Dev and test only. */
export type MemoryTwin = {
  source: TwinSource;
  /** Current state, as a copy. */
  current: () => StoreResponse;
  /** Applies a change, bumps the context version, and pushes the new state to subscribers. */
  update: (change: (state: StoreResponse) => StoreResponse) => StoreResponse;
  /** Open subscriptions, to check that the scene lets go of the feed. */
  listenerCount: () => number;
};

function nextVersion(state: StoreResponse): Pick<StoreResponse, "context_version" | "version"> {
  const version = `v${(contextRevision(state.context_version) ?? 0) + 1}`;
  return { context_version: `${state.store_id}:${version}`, version };
}

export function createMemoryTwin(initial: StoreResponse): MemoryTwin {
  let state = structuredClone(initial);
  const listeners = new Set<(state: StoreResponse) => void>();

  return {
    source: {
      snapshot: () => Promise.resolve(structuredClone(state)),
      subscribe: (onState) => {
        listeners.add(onState);
        return () => listeners.delete(onState);
      },
    },
    current: () => structuredClone(state),
    update: (change) => {
      const changed = change(structuredClone(state));
      state = { ...changed, ...nextVersion(state) };
      for (const listener of listeners) listener(structuredClone(state));
      return structuredClone(state);
    },
    listenerCount: () => listeners.size,
  };
}

/**
 * `state` with one product's fields replaced and its record version bumped, or with
 * the product removed when `patch` is null. Fields may be set to invalid values on
 * purpose, to check how the scene copes.
 */
export function patchProduct(
  state: StoreResponse,
  sku: string,
  patch: Partial<Record<keyof ProductInventory, unknown>> | null,
): StoreResponse {
  const products = state.products.flatMap((product) => {
    if (product.sku !== sku) return [product];
    if (patch === null) return [];
    return [{ ...product, ...patch, version: product.version + 1 } as ProductInventory];
  });
  return { ...state, products };
}
