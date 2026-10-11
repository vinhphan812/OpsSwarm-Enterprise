import type { MemoryTwin } from "@/core/api/sources/memorySource";
import {
  GUARD_VERDICT,
  REVIEW_DECISION,
  REVIEW_REASON,
  SIMULATION_STATUS,
  type ReviewDecision,
  type ReviewReason,
} from "@/enums/simulation.enum";
import { simulationOf, DEMO_ACTIONS } from "@/fixtures/demo/simulation";
import { useTwinStore } from "@/state/twin.store";
import type { ReviewResult, Simulation, SimulationAction } from "@/types/simulation.type";
import type { SimulationReviewer } from "./simulationReview";

/**
 * Simulations on the in-memory twin, driven from the browser console under
 * `?twin=memory|demo` (`twin.simulate()`, `twin.commit()`, `twin.discard()`) and from the
 * banner's Accept and Reject buttons. They stand in for the simulation API, the review
 * routes, and the guarded commit. Development builds only.
 */

let runs = 0;

/** Opens a simulation of `actions` (the demo actions by default) on the twin's current state. Returns its id. */
export function openSimulation(twin: MemoryTwin, actions: SimulationAction[] = DEMO_ACTIONS): string {
  runs += 1;
  const simulation = simulationOf(twin.current(), actions, `sim-memory-${String(runs).padStart(3, "0")}`);
  useTwinStore.getState().setSimulation(simulation);
  return simulation.simulation_id;
}

/**
 * Reviews `simulation` the way the backend would. Both decisions are bound to the
 * proposal that was reviewed: once the open run's proposal has been replaced (same id,
 * newer `state.context_version`), either is refused with `proposal_changed` and the run
 * stays open. A rejection then closes the run; Live moving on does not stop it, since a
 * rejection never writes Live. An approval goes through a minimal guard that answers
 * REFRESH_REQUIRED (`live_moved`) once Live has moved on since the simulation started,
 * and ALLOW otherwise. On ALLOW the proposed state is written to the twin, which pushes it
 * to the live feed; the web app's Live view changes only through that feed. Throws when
 * `simulation` is not the open one.
 */
export function reviewOnTwin(twin: MemoryTwin, simulation: Simulation, decision: ReviewDecision): ReviewResult {
  const { simulation: open, setSimulation } = useTwinStore.getState();
  if (!open || open.simulation_id !== simulation.simulation_id) {
    throw new Error(`${simulation.simulation_id} is not open.`);
  }
  const result = { simulation_id: simulation.simulation_id, decision, reason_code: null, live_context_version: null };
  const reject = decision === REVIEW_DECISION.Reject;
  const refused = (reason_code: ReviewReason): ReviewResult => ({
    ...result,
    status: SIMULATION_STATUS.Evaluated,
    verdict: reject ? null : GUARD_VERDICT.RefreshRequired,
    reason_code,
  });
  if (open.state.context_version !== simulation.state.context_version) return refused(REVIEW_REASON.ProposalChanged);
  if (reject) {
    setSimulation(null);
    return { ...result, status: SIMULATION_STATUS.Rejected, verdict: null };
  }
  if (twin.current().context_version !== simulation.base_context_version) return refused(REVIEW_REASON.LiveMoved);
  const committed = twin.update(() => structuredClone(simulation.state));
  setSimulation(null);
  return {
    ...result,
    status: SIMULATION_STATUS.Committed,
    verdict: GUARD_VERDICT.Allow,
    live_context_version: committed.context_version,
  };
}

/** The banner's reviewer on the memory twin. */
export function createMemoryReviewer(twin: MemoryTwin): SimulationReviewer {
  return async (simulation, decision) => reviewOnTwin(twin, simulation, decision);
}

/** `twin.commit()`: approves the open simulation. Returns the new live context version, or throws when refused. */
export function commitSimulation(twin: MemoryTwin): string {
  const { simulation } = useTwinStore.getState();
  if (!simulation) throw new Error("No simulation is open.");
  const result = reviewOnTwin(twin, simulation, REVIEW_DECISION.Approve);
  if (result.verdict !== GUARD_VERDICT.Allow) {
    throw new Error(
      `${result.verdict}: ${simulation.simulation_id} started from ${simulation.base_context_version}, Live is now ${twin.current().context_version}.`,
    );
  }
  return result.live_context_version!;
}

/** Drops the open simulation without touching Live. */
export function discardSimulation() {
  useTwinStore.getState().setSimulation(null);
}
