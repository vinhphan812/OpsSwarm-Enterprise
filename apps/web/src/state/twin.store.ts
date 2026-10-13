import { create } from "zustand";
import type { StoreResponse } from "@/types/twin.type";
import type { Simulation } from "@/types/simulation.type";
import type { ProductIssue } from "@/core/api/validate";
import { diffStates, isEmptyDiff, type StateDiff } from "@/core/twin/stateDiff";
import { TWIN_STATUS, type TwinStatus } from "@/enums/twin.enum";
import { VIEW_MODE, type ViewMode } from "@/enums/ui.enum";

/**
 * A change and when it appeared, in ms since the epoch. `before` is the state it was
 * diffed from (the previous Live state, or Live for a proposal), so a cue can still draw
 * what was there, such as a moved product's old facings at its source slot.
 */
export type RecentChange = { diff: StateDiff; at: number; before: StoreResponse };

type TwinStore = {
  live: StoreResponse | null;
  /** Products of the last live state that broke the contract and were left out of it. */
  issues: ProductIssue[];
  /** The last Live → Live change, with the Live state before it; a state that changed nothing leaves it as it was. */
  liveChange: RecentChange | null;
  /** The open Simulation Twin run, or null. Kept apart from `live`: nothing copies one into the other. */
  simulation: Simulation | null;
  /** When the open simulation's proposed state last changed; 0 before any. */
  simulationChangedAt: number;
  /**
   * The proposal the scene showed when its run was rejected or discarded, and when, so the
   * scene can carry its changes back to Live. Never set for an approval: Live then changes
   * through its feed.
   */
  leftProposal: { state: StoreResponse; at: number } | null;
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
  leaveProposal: (state: StoreResponse) => void;
  setStatus: (status: TwinStatus, error?: string | null) => void;
  setStale: (stale: boolean) => void;
  retry: () => void;
};

/** Read-side copy of twin state from apps/api. Never the source of truth. */
export const useTwinStore = create<TwinStore>()((set) => ({
  live: null,
  issues: [],
  liveChange: null,
  simulation: null,
  simulationChangedAt: 0,
  leftProposal: null,
  status: TWIN_STATUS.Loading,
  error: null,
  stale: false,
  attempt: 0,
  setLive: (live, issues = []) =>
    set((twin) => {
      // The first state is a load, not a change.
      const diff = twin.live ? diffStates(twin.live, live) : null;
      const liveChange =
        twin.live && diff && !isEmptyDiff(diff) ? { diff, at: Date.now(), before: twin.live } : twin.liveChange;
      return { live, issues, liveChange, stale: false };
    }),
  setSimulation: (simulation) =>
    set((twin) => ({
      simulation,
      simulationChangedAt:
        simulation && simulation.state !== twin.simulation?.state ? Date.now() : twin.simulationChangedAt,
    })),
  leaveProposal: (state) => set({ leftProposal: { state, at: Date.now() } }),
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
