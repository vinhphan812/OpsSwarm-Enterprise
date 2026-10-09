import { create } from "zustand";
import type { StoreResponse } from "@/types/twin.type";
import type { ProductIssue } from "@/core/api/validate";
import { TWIN_STATUS, type TwinStatus } from "@/enums/twin.enum";

type TwinStore = {
  live: StoreResponse | null;
  /** Products of the last live state that broke the contract and were left out of it. */
  issues: ProductIssue[];
  simulation: StoreResponse | null;
  /** Loading until the first live state; error when it could not be loaded. */
  status: TwinStatus;
  /** Readable reason for the error status. */
  error: string | null;
  /** The live feed dropped after loading; `live` is the last state received. */
  stale: boolean;
  /** Bumped by `retry`; the connection reconnects when it changes. */
  attempt: number;
  setLive: (state: StoreResponse, issues?: ProductIssue[]) => void;
  setSimulation: (state: StoreResponse | null) => void;
  setStatus: (status: TwinStatus, error?: string | null) => void;
  setStale: (stale: boolean) => void;
  retry: () => void;
};

/** Read-side copy of twin state from apps/api. Never the source of truth. */
export const useTwinStore = create<TwinStore>()((set) => ({
  live: null,
  issues: [],
  simulation: null,
  status: TWIN_STATUS.Loading,
  error: null,
  stale: false,
  attempt: 0,
  setLive: (live, issues = []) => set({ live, issues, stale: false }),
  setSimulation: (simulation) => set({ simulation }),
  setStatus: (status, error = null) => set({ status, error }),
  setStale: (stale) => set({ stale }),
  retry: () => set((state) => ({ attempt: state.attempt + 1 })),
}));
