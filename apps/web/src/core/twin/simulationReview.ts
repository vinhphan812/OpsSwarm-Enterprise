import { defaultClient } from "@/core/api/client";
import { parseReviewResult } from "@/core/api/validate";
import type { ReviewDecision } from "@/enums/simulation.enum";
import type { RetailTwinClient } from "@/types/api.type";
import type { ReviewRequest, ReviewResult, Simulation } from "@/types/simulation.type";

/**
 * Sends a person's approval or rejection of a proposal to whatever decides on it: the
 * guard and the Executor in apps/api, or the memory twin's stand-in while developing.
 * It never changes the twin state on screen itself; Live changes only through its feed.
 */
export type SimulationReviewer = (simulation: Simulation, decision: ReviewDecision) => Promise<ReviewResult>;

/** What the reviewer looked at, so a review of a proposal or a Live state that has moved on is refused. */
export function reviewRequestOf(simulation: Simulation): ReviewRequest {
  return {
    base_context_version: simulation.base_context_version,
    proposal_context_version: simulation.state.context_version,
  };
}

/**
 * Reviews through `POST /simulations/{simulation_id}/approve|reject` on apps/api.
 * TODO(BE): apps/api serves neither route yet, so every review fails with a toast until it does.
 */
export function createApiReviewer(client: RetailTwinClient = defaultClient): SimulationReviewer {
  return async (simulation, decision) =>
    parseReviewResult(await client.reviewSimulation(simulation.simulation_id, decision, reviewRequestOf(simulation)));
}
