/** Where a run stands on one stage of the control loop, as its entries show it. */
export const STAGE_STATUS = {
  /** The run has an entry for the stage and has moved on, or has finished. */
  Done: "done",
  /** The stage of the run's latest entry, while the run has not reached VERIFY. */
  Active: "active",
  /** No entry for the stage yet. Never filled in by the UI. */
  Pending: "pending",
} as const;
export type StageStatus = (typeof STAGE_STATUS)[keyof typeof STAGE_STATUS];

/** How the Operations timeline shows the agent's activity. */
export const ACTIVITY_VIEW = {
  /** One card per run, with the control loop as a stepper. */
  Runs: "runs",
  /** Every entry as one line, oldest first. */
  Log: "log",
} as const;
export type ActivityView = (typeof ACTIVITY_VIEW)[keyof typeof ACTIVITY_VIEW];
export const ACTIVITY_VIEWS: readonly ActivityView[] = Object.values(ACTIVITY_VIEW);
