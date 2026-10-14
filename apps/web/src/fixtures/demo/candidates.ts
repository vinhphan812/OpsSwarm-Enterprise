import { ACTION_TYPE } from "@/enums/simulation.enum";
import type { Candidate, SimulationAction } from "@/types/simulation.type";
import type { StoreResponse } from "@/types/twin.type";
import { DEMO_ACTIONS, DEMO_SIMULATION_ID, simulationOf } from "./simulation";
import { demoStoreState } from "./store";

/**
 * Demo data for `?twin=demo` (development builds only), never Simulation Twin truth.
 * Alternative proposals of the demo simulation, as `GET /simulations/{id}/candidates`
 * serves them (#83). KPI values and justifications are demo data for the UI (#93).
 */

/** Each candidate's actions: the whole demo plan, restocking only, or moves only. */
const DEMO_CANDIDATE_ACTIONS: Record<string, SimulationAction[]> = {
  "cand-a": DEMO_ACTIONS,
  "cand-b": [
    { type: ACTION_TYPE.ReplenishShelf, sku: "P003", quantity: 12 },
    { type: ACTION_TYPE.ChangeFacings, sku: "P004", facings: 4 },
  ],
  "cand-c": DEMO_ACTIONS.filter((action) => action.type === ACTION_TYPE.MoveProduct),
};

/** KPI scores for demo candidates. */
const DEMO_CANDIDATE_KPIS: Record<string, CandidateKPI[]> = {
  "cand-a": [
    { name: "Revenue Impact", value: 1240.5, unit: "$", source: "evaluator-v1" },
    { name: "Stockout Risk", value: 12, unit: "%", source: "evaluator-v1" },
  ],
  "cand-b": [
    { name: "Revenue Impact", value: 380.2, unit: "$", source: "evaluator-v1" },
    { name: "Stockout Risk", value: 28, unit: "%", source: "evaluator-v1" },
  ],
  "cand-c": [
    { name: "Revenue Impact", value: 860.3, unit: "$", source: "evaluator-v1" },
    { name: "Stockout Risk", value: 8, unit: "%", source: "evaluator-v1" },
  ],
};

/** Agent justifications for demo candidates. */
const DEMO_CANDIDATE_JUSTIFICATIONS: Record<string, string> = {
  "cand-a":
    "Full restocking and shelf optimization — maximizes revenue with moderate stockout risk. " +
    "Prioritizes high-velocity SKUs and clears low-facings dead stock.",
  "cand-b":
    "Conservative restocking of P003 with targeted facings adjustment for P004. " +
    "Lower revenue uplift but significantly reduces stockout exposure.",
  "cand-c":
    "Movement-only plan: relocates products to better-performing slots without adding inventory. " +
    "Best stockout risk profile; suitable for inventory-constrained periods.",
};

type CandidateKPI = import("@/types/simulation.type").CandidateKPI;

/** `actions` on `base` as candidate `candidateId` of `simulationId`, with a proposal version of its own. */
export function candidateOf(
  base: StoreResponse,
  candidateId: string,
  actions: SimulationAction[],
  simulationId = DEMO_SIMULATION_ID,
): Candidate {
  const { state } = simulationOf(base, actions, simulationId);
  return {
    candidate_id: candidateId,
    simulation_id: simulationId,
    proposed_actions: structuredClone(actions),
    // Its own proposal version, so a review of one candidate is refused once another is on screen.
    state: { ...state, context_version: `${simulationId}:${candidateId}` },
    kpis: structuredClone(DEMO_CANDIDATE_KPIS[candidateId] ?? []),
    evaluator_version: "evaluator-v1",
    justification: DEMO_CANDIDATE_JUSTIFICATIONS[candidateId] ?? "No justification provided.",
  };
}

/** The demo candidates of the demo simulation on `base`, the demo store by default. */
export function demoCandidates(base: StoreResponse = demoStoreState()): Candidate[] {
  return Object.entries(DEMO_CANDIDATE_ACTIONS).map(([id, actions]) => candidateOf(base, id, actions));
}
