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
