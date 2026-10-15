import { ACTION_TYPE, BASELINE_CANDIDATE_ID, type KpiName } from "@/enums/simulation.enum";
import type { Candidate, SimulationAction } from "@/types/simulation.type";
import type { StoreResponse } from "@/types/twin.type";
import { DEMO_ACTIONS, DEMO_SIMULATION_ID, simulationOf } from "./simulation";
import { demoStoreState } from "./store";

/**
 * Demo data for `?twin=demo` (development builds only), never Simulation Twin truth.
 * Alternative proposals of the demo simulation, as `GET /simulations/{id}/candidates`
 * serves them (#83), with the `baseline` candidate that holds the "before" of every KPI (#39).
 * KPI values and provenances are demo data for the UI.
 */

/** Each candidate's actions: none for the baseline, the whole demo plan, restocking only, or moves only. */
const DEMO_CANDIDATE_ACTIONS: Record<string, SimulationAction[]> = {
  [BASELINE_CANDIDATE_ID]: [],
  "cand-a": DEMO_ACTIONS,
  "cand-b": [
    { type: ACTION_TYPE.ReplenishShelf, sku: "P003", quantity: 12 },
    { type: ACTION_TYPE.ChangeFacings, sku: "P004", facings: 4 },
  ],
  "cand-c": DEMO_ACTIONS.filter((action) => action.type === ACTION_TYPE.MoveProduct),
};

/**
 * Scores in the shape of the `simulation-kpi-v1` evaluator (services/simulation, #33):
 * shares of horizon demand in hundredths, with
 * `business_score = revenue_benefit + 0 * margin_benefit + service_level - stockout_risk - movement_cost`.
 * Demo values, not computed by the evaluator.
 */
const DEMO_SCORES: Record<string, Record<KpiName, number>> = {
  [BASELINE_CANDIDATE_ID]: { stockout_risk: 0.4, service_level: 0.35, movement_cost: 0, revenue_benefit: 0, margin_benefit: 0, business_score: -0.05 },
  "cand-a": { stockout_risk: 0.1, service_level: 0.8, movement_cost: 0.3, revenue_benefit: 0.45, margin_benefit: 0, business_score: 0.85 },
  "cand-b": { stockout_risk: 0.15, service_level: 0.75, movement_cost: 0.12, revenue_benefit: 0.4, margin_benefit: 0, business_score: 0.88 },
  "cand-c": { stockout_risk: 0.4, service_level: 0.35, movement_cost: 0.15, revenue_benefit: 0.05, margin_benefit: 0, business_score: -0.15 },
};

/** The evaluator id the demo scores are shaped after. */
export const DEMO_EVALUATOR = "simulation-kpi-v1";

/** Provenance of the demo candidates, as the agent would describe each plan. */
const DEMO_CANDIDATE_PROVENANCES: Record<string, string> = {
  [BASELINE_CANDIDATE_ID]: "No actions: the run's base state, scored for comparison.",
  "cand-a":
    "Full restocking and shelf optimization: restock P003, re-face P004, and move P007, P008 and P005. " +
    "Best service level, at the highest movement cost.",
  "cand-b":
    "Conservative restocking of P003 with targeted facings adjustment for P004. " +
    "Nearly the same service level as the full plan for far less movement.",
  "cand-c":
    "Movement-only plan: relocates products to better-performing slots without adding inventory. " +
    "Leaves the stockout risk where it is.",
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
    kpis: Object.entries(DEMO_SCORES[candidateId] ?? {}).map(([name, value]) => ({ name, value, unit: "share", source: DEMO_EVALUATOR })),
    evaluator_version: DEMO_EVALUATOR,
    provenance: DEMO_CANDIDATE_PROVENANCES[candidateId] ?? "No provenance provided.",
  };
}

/** The demo candidates of the demo simulation, baseline first, on `base`, the demo store by default. */
export function demoCandidates(base: StoreResponse = demoStoreState()): Candidate[] {
  return Object.entries(DEMO_CANDIDATE_ACTIONS).map(([id, actions]) => candidateOf(base, id, actions));
}
