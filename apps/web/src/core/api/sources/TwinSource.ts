import type { StoreResponse } from "@/types/twin.type";

/**
 * Read-only feed of Live Twin state. The web app never writes through a source.
 */
export interface TwinSource {
  /** Current state at the time of the call. Rejects when the twin cannot be reached. */
  snapshot(): Promise<StoreResponse>;
  /**
   * Calls `onState` for each later state, and `onError` when the live feed drops.
   * Returns the unsubscribe function.
   */
  subscribe(onState: (state: StoreResponse) => void, onError?: (error: unknown) => void): () => void;
}
