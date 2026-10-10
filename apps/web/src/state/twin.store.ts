import { create } from "zustand";
import type { StoreResponse } from "@/types/twin.type";
import type { Simulation } from "@/types/simulation.type";
import type { ProductIssue } from "@/core/api/validate";
import { TWIN_STATUS, type TwinStatus } from "@/enums/twin.enum";
import { VIEW_MODE, type ViewMode } from "@/enums/ui.enum";

type TwinStore = {
  live: StoreResponse | null;
  /** Products of the last live state that broke the contract and were left out of it. */
  issues: ProductIssue[];
  /** The open Simulation Twin run, or null. Kept apart from `live`: nothing copies one into the other. */
  simulation: Simulation | null;
  /** Loading until the first live state; error when it could not be loaded. */
  status: TwinStatus;
  /** Readable reason for the error status. */
  error: string | null;
  /** The live feed dropped after loading; `live` is the last state received. */
  stale: boolean;
  /** Bumped by `retry`; the connection reconnects when it changes. */
  attempt: number;
  setLive: (state: StoreResponse, issues?: ProductIssue[]) => void;
  setSimulation: (simulation: Simulation | null) => void;
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

/** The simulation the scene shows: the open one while the Simulation view is picked, else null. */
export function shownSimulation(twin: Pick<TwinStore, "simulation">, viewMode: ViewMode): Simulation | null {
  return viewMode === VIEW_MODE.Simulation ? twin.simulation : null;
}

/**
 * The twin state the scene and the inspectors show: the simulation's proposed state in the
 * Simulation view, the live state otherwise. Without an open simulation it is always Live.
 */
export function activeState(twin: Pick<TwinStore, "live" | "simulation">, viewMode: ViewMode): StoreResponse | null {
  return shownSimulation(twin, viewMode)?.state ?? twin.live;
}
