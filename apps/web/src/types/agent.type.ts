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
  sku?: string;
  /** The shelf or piece of equipment the entry is about; focused when there is no SKU. */
  shelf_id?: string;
  slot_id?: string;
};
