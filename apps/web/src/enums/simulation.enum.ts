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

/**
 * A person's answer to an evaluated proposal, as the FE names it. apps/api answers with
 * `approved` / `rejected`; `parseReviewResult` maps those back to these.
 */
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

/**
 * Why a review ended as it did (`ReviewResult.reason_code`). The upper-case codes are the ones
 * apps/api serves (`DecisionReviewReasonCode`); the lower-case ones are the memory twin's.
 */
export const REVIEW_REASON = {
  /** Live is no longer at the proposal's `base_context_version`. Refuses an approval only. */
  LiveMoved: "live_moved",
  /** The run's proposal was replaced since it was reviewed. Refuses an approval and a rejection. */
  ProposalChanged: "proposal_changed",
  /** The review was sent against a Live version that has moved on; checked before the guard runs. */
  VersionMismatch: "VERSION_MISMATCH",
  /** The guard found Live newer than the decision's context. */
  VersionStale: "VERSION_STALE",
} as const;
export type ReviewReason = (typeof REVIEW_REASON)[keyof typeof REVIEW_REASON];

/** The Decision Context Guard's gates, in the order it runs them (`GATES` in the apps/api guard). */
export const GUARD_GATE = {
  Integrity: "integrity",
  Evidence: "evidence",
  Context: "context",
  Freshness: "freshness",
  Feasibility: "feasibility",
  Policy: "policy",
} as const;
export type GuardGate = (typeof GUARD_GATE)[keyof typeof GUARD_GATE];
export const GUARD_GATES: readonly string[] = Object.values(GUARD_GATE);

/**
 * KPI names a candidate is scored on: the fields of the `simulation-kpi-v1` evaluator
 * (services/simulation, #33), each a share of horizon demand. TODO(BE): FE proposal for
 * `CandidateKPI.name` in `GET /simulations/{simulation_id}/candidates` (#83).
 */
export const KPI_NAME = {
  StockoutRisk: "stockout_risk",
  ServiceLevel: "service_level",
  MovementCost: "movement_cost",
  RevenueBenefit: "revenue_benefit",
  MarginBenefit: "margin_benefit",
  BusinessScore: "business_score",
} as const;
export type KpiName = (typeof KPI_NAME)[keyof typeof KPI_NAME];

/** KPIs where a lower value is the better one; every other KPI is better higher. */
export const LOWER_IS_BETTER_KPIS: readonly string[] = [KPI_NAME.StockoutRisk, KPI_NAME.MovementCost];

/**
 * The candidate with no actions, scored on the run's base state: the "before" of every
 * other candidate. TODO(BE): FE proposal; the evaluator already scores it under this id.
 */
export const BASELINE_CANDIDATE_ID = "baseline";

/** How a KPI moved against the baseline, in the KPI's own direction. */
export const KPI_TREND = {
  Better: "better",
  Worse: "worse",
  Same: "same",
} as const;
export type KpiTrend = (typeof KPI_TREND)[keyof typeof KPI_TREND];
