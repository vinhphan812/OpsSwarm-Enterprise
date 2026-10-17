export type ControlStage =
  | "OBSERVE"
  | "DETECT"
  | "INVESTIGATE"
  | "PLAN"
  | "SIMULATE"
  | "GUARD"
  | "ACT"
  | "VERIFY";

export type GuardVerdict = "ALLOW" | "REFRESH_REQUIRED" | "DENY";

/** One line of the Agent Activity timeline. A summary, never model reasoning. */
export type ActivityEntry = {
  id: string;
  ts: string;
  stage: ControlStage;
  summary: string;
  correlation_id?: string;
  decision_id?: string;
  /** The simulation the entry is about, as `GET /agent/events` serves it. */
  simulation_id?: string;
  /** The stage's outcome as `GET /agent/events` serves it; on VERIFY, the verifier's report status. */
  status?: string;
  sku?: string;
  /** The shelf or piece of equipment the entry is about; focused when there is no SKU. */
  shelf_id?: string;
  slot_id?: string;
  simulation_id?: string;
};
