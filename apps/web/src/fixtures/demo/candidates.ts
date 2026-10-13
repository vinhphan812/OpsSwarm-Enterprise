import { ACTION_TYPE } from "@/enums/simulation.enum";
import type { Candidate, SimulationAction } from "@/types/simulation.type";
import type { StoreResponse } from "@/types/twin.type";
import { DEMO_ACTIONS, DEMO_SIMULATION_ID, simulationOf } from "./simulation";
import { demoStoreState } from "./store";

/**
 * Demo data for `?twin=demo` (development builds only), never Simulation Twin truth.
 * Alternative proposals of the demo simulation, as `GET /simulations/{id}/candidates`
 * will serve them (#83), without KPI values: those come from apps/api only (#93).
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
  };
}

/** The demo candidates of the demo simulation on `base`, the demo store by default. */
export function demoCandidates(base: StoreResponse = demoStoreState()): Candidate[] {
  return Object.entries(DEMO_CANDIDATE_ACTIONS).map(([id, actions]) => candidateOf(base, id, actions));
}
