/** Where a simulation run stands. TODO(BE): agree the values with the simulation API. */
export const SIMULATION_STATUS = {
  /** Being evaluated; the proposed state may still change. */
  Pending: "pending",
  /** Evaluated and waiting for the guard. */
  Evaluated: "evaluated",
  /** Passed the guard and applied to the Live Twin. */
  Committed: "committed",
  /** Denied by the guard or discarded. */
  Rejected: "rejected",
} as const;
export type SimulationStatus = (typeof SIMULATION_STATUS)[keyof typeof SIMULATION_STATUS];

/** MVP simulation actions (docs/DOMAIN_AND_DATA_MODEL.md §8). */
export const ACTION_TYPE = {
  MoveProduct: "move_product",
  ChangeFacings: "change_facings",
  ReplenishShelf: "replenish_shelf",
} as const;
export type ActionType = (typeof ACTION_TYPE)[keyof typeof ACTION_TYPE];

/** A person's answer to an evaluated proposal. TODO(BE): FE proposal for the review routes. */
export const REVIEW_DECISION = {
  /** Send the proposal to the guard; the Executor commits it only on ALLOW. */
  Approve: "approve",
  /** Close the proposal without touching Live. */
  Reject: "reject",
} as const;
export type ReviewDecision = (typeof REVIEW_DECISION)[keyof typeof REVIEW_DECISION];

/** The Decision Context Guard's answer, `DCGVerdict` in contracts/TECHNICAL_SPEC.md §7. */
export const GUARD_VERDICT = {
  Allow: "ALLOW",
  Deny: "DENY",
  RefreshRequired: "REFRESH_REQUIRED",
  HumanReview: "HUMAN_REVIEW",
} as const;
export type GuardVerdict = (typeof GUARD_VERDICT)[keyof typeof GUARD_VERDICT];

/** Why a review was refused without a commit (`ReviewResult.reason_code`). TODO(BE): FE proposal for the review routes. */
export const REVIEW_REASON = {
  /** Live is no longer at the proposal's `base_context_version`. Refuses an approval only. */
  LiveMoved: "live_moved",
  /** The run's proposal was replaced since it was reviewed. Refuses an approval and a rejection. */
  ProposalChanged: "proposal_changed",
} as const;
export type ReviewReason = (typeof REVIEW_REASON)[keyof typeof REVIEW_REASON];
