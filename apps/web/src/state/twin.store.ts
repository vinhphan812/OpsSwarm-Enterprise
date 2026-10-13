import { create } from "zustand";
import type { StoreResponse } from "@/types/twin.type";
import type { Candidate, Simulation } from "@/types/simulation.type";
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
  /** Alternative proposals of the open simulation; empty when it has none. */
  candidates: Candidate[];
  /** The candidate the Simulation view shows, or null for the simulation's own proposal. */
  selectedCandidateId: string | null;
  /** When the proposal on screen in the Simulation view last changed or was switched; 0 before any. */
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
  /** Replaces the candidates; the selection survives while its candidate is still among them. */
  setCandidates: (candidates: Candidate[]) => void;
  /** Shows candidate `id` in the Simulation view; null goes back to the simulation's own proposal. */
  selectCandidate: (id: string | null) => void;
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
  candidates: [],
  selectedCandidateId: null,
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
    set((twin) => {
      // Candidates belong to one run: another run, or none, drops them.
      const sameRun = simulation !== null && simulation.simulation_id === twin.simulation?.simulation_id;
      const candidates = sameRun
        ? { candidates: twin.candidates, selectedCandidateId: twin.selectedCandidateId }
        : { candidates: [], selectedCandidateId: null };
      const before = proposalState(twin);
      const after = proposalState({ ...twin, ...candidates, simulation });
      return {
        simulation,
        ...candidates,
        simulationChangedAt: after && after !== before ? Date.now() : twin.simulationChangedAt,
      };
    }),
  setCandidates: (candidates) =>
    set((twin) => {
      const selectedCandidateId = candidates.some((candidate) => candidate.candidate_id === twin.selectedCandidateId)
        ? twin.selectedCandidateId
        : null;
      const next = { ...twin, candidates, selectedCandidateId };
      const changed = proposalState(next) !== proposalState(twin);
      return { candidates, selectedCandidateId, simulationChangedAt: changed ? Date.now() : twin.simulationChangedAt };
    }),
  selectCandidate: (selectedCandidateId) =>
    set((twin) =>
      twin.selectedCandidateId === selectedCandidateId ? {} : { selectedCandidateId, simulationChangedAt: Date.now() },
    ),
  leaveProposal: (state) => set({ leftProposal: { state, at: Date.now() } }),
  setStatus: (status, error = null) => set({ status, error }),
  setStale: (stale) => set({ stale }),
  retry: () => set((state) => ({ attempt: state.attempt + 1 })),
}));

type ProposalSource = Pick<TwinStore, "simulation"> & Partial<Pick<TwinStore, "candidates" | "selectedCandidateId">>;

/** The selected candidate of the open simulation, or null. */
export function selectedCandidate(twin: ProposalSource): Candidate | null {
  const { simulation, candidates = [], selectedCandidateId = null } = twin;
  if (!simulation || selectedCandidateId === null) return null;
  return (
    candidates.find(
      (candidate) =>
        candidate.candidate_id === selectedCandidateId && candidate.simulation_id === simulation.simulation_id,
    ) ?? null
  );
}

/** The last run shown with a candidate's proposal, so a selector returns the same object until either changes. */
let lastProposal: { simulation: Simulation; candidate: Candidate; shown: Simulation } | null = null;

/** The open simulation with the selected candidate's proposal, or as it is when none is selected. */
function proposalOf(twin: ProposalSource): Simulation | null {
  const candidate = selectedCandidate(twin);
  if (!twin.simulation || !candidate) return twin.simulation;
  if (lastProposal?.simulation !== twin.simulation || lastProposal.candidate !== candidate) {
    const shown = { ...twin.simulation, actions: candidate.proposed_actions, state: candidate.state };
    lastProposal = { simulation: twin.simulation, candidate, shown };
  }
  return lastProposal.shown;
}

/** The proposed state the Simulation view shows, or null without an open simulation. */
function proposalState(twin: ProposalSource): StoreResponse | null {
  return proposalOf(twin)?.state ?? null;
}

/**
 * The simulation the scene shows, while the Simulation view is picked, else null: the
 * open one, carrying the selected candidate's actions and state when one is selected.
 */
export function shownSimulation(twin: ProposalSource, viewMode: ViewMode): Simulation | null {
  return viewMode === VIEW_MODE.Simulation ? proposalOf(twin) : null;
}

/**
 * The twin state the scene and the inspectors show: the proposed state (the selected
 * candidate's, else the simulation's) in the Simulation view, the live state otherwise. Without an open simulation it is always Live.
 */
export function activeState(twin: ProposalSource & Pick<TwinStore, "live">, viewMode: ViewMode): StoreResponse | null {
  return shownSimulation(twin, viewMode)?.state ?? twin.live;
}
