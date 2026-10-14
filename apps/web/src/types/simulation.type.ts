import type { ACTION_TYPE, GuardVerdict, ReviewDecision, SimulationStatus } from "@/enums/simulation.enum";
import type { StoreResponse } from "./twin.type";

export type MoveProductAction = {
  type: typeof ACTION_TYPE.MoveProduct;
  sku: string;
  from_slot: string;
  to_slot: string;
};

export type ChangeFacingsAction = {
  type: typeof ACTION_TYPE.ChangeFacings;
  sku: string;
  facings: number;
};

export type ReplenishShelfAction = {
  type: typeof ACTION_TYPE.ReplenishShelf;
  sku: string;
  quantity: number;
};

/** One proposed change; `ActionUnion` in contracts/TECHNICAL_SPEC.md. */
export type SimulationAction = MoveProductAction | ChangeFacingsAction | ReplenishShelfAction;

/**
 * A Simulation Twin run, as `GET /simulations/{simulation_id}` will serve it.
 * TODO(BE): apps/api serves no simulations yet; this shape is the FE's proposal (#26).
 */
export type Simulation = {
  simulation_id: string;
  store_id: string;
  /** Live state the simulation started from, as `StoreResponse.context_version`. */
  base_context_version: string;
  status: SimulationStatus;
  actions: SimulationAction[];
  /** The proposed store: Live at `base_context_version` with `actions` applied. Never Live truth. */
  state: StoreResponse;
};

/**
 * One alternative proposal of a simulation run, matching `SimulationCandidateResponse`
 * from `GET /simulations/{simulation_id}/candidates` (#83). KPI values and provenance
 * come from the evaluator (bound in #93) and are never computed locally.
 */
export type CandidateKPI = {
  /** Human-readable KPI name, e.g. "Revenue Impact". */
  name: string;
  /** Numeric value of the KPI. */
  value: number;
  /** Unit of the value, e.g. "$" or "%". */
  unit: string;
  /** Which evaluator produced this KPI. */
  source: string;
};

export type Candidate = {
  candidate_id: string;
  simulation_id: string;
  proposed_actions: SimulationAction[];
  /** The proposed store with `proposed_actions` applied. Never Live truth. */
  state: StoreResponse;
  /** Evaluator-produced KPIs for this candidate. Empty when no evaluator has scored it. */
  kpis: CandidateKPI[];
  /** Version of the evaluator that produced these KPIs. */
  evaluator_version: string;
  /** Provenance of this candidate. */
  provenance: string;
};

/** `GET /simulations/{simulation_id}/candidates`. */
export type CandidatesResponse = {
  candidates: Candidate[];
};
/** One row of `GET /simulations?status=open`. TODO(BE): FE proposal (#26). */
export type SimulationSummary = Pick<Simulation, "simulation_id" | "store_id" | "base_context_version" | "status">;

/** `GET /simulations?status=open`. TODO(BE): FE proposal (#26). */
export type SimulationsResponse = { simulations: SimulationSummary[] };

/**
 * Body of `POST /simulations/{simulation_id}/approve` and `/reject`: what the reviewer
 * looked at, so the backend can refuse a review of something that has changed since.
 * TODO(BE): apps/api serves neither route yet; this shape is the FE's proposal.
 */
export type ReviewRequest = {
  /** The Live version the proposal was built on, as the reviewer saw it. */
  base_context_version: string;
  /** The proposed state the reviewer saw, as `Simulation.state.context_version`. */
  proposal_context_version: string;
};

/**
 * The answer to a review. An approval is not a commit: the guard decides, and only on
 * ALLOW does the Executor apply the actions. Live then changes through `GET /store`.
 * TODO(BE): FE proposal, see `ReviewRequest`.
 */
export type ReviewResult = {
  simulation_id: string;
  decision: ReviewDecision;
  /** The run's status after the review: committed, rejected, or still evaluated when the guard refused. */
  status: SimulationStatus;
  /** The guard's verdict on an approval; null for a rejection. */
  verdict: GuardVerdict | null;
  /** Why the guard answered as it did (`DCGVerdictResult.reason_code`), or null. */
  reason_code: string | null;
  /** Live version after an executed commit, else null. */
  live_context_version: string | null;
};
