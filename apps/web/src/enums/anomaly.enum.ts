/** What the detector found, as apps/api `AnomalyType` serves it (`GET /anomalies`). */
export const ANOMALY_TYPE = {
  /** Nothing left on the shelf. */
  Stockout: "stockout",
  /** Demand rose above forecast: an opportunity, not a fault. */
  DemandSurge: "demand_surge",
  /** Sales below forecast while the shelf is stocked. */
  SlowMoving: "slow_moving",
  /** More stock than the product sells. */
  ExcessInventory: "excess_inventory",
  /** The price charged does not match the expected one. */
  PriceAnomaly: "price_anomaly",
  /** The shelf breaks its planogram. */
  ShelfViolation: "shelf_violation",
} as const;
export type AnomalyType = (typeof ANOMALY_TYPE)[keyof typeof ANOMALY_TYPE];

/** As apps/api `AnomalySeverity`, mildest first. */
export const ANOMALY_SEVERITY = {
  Low: "low",
  Medium: "medium",
  High: "high",
  Critical: "critical",
} as const;
export type AnomalySeverity = (typeof ANOMALY_SEVERITY)[keyof typeof ANOMALY_SEVERITY];
export const ANOMALY_TYPES: readonly AnomalyType[] = Object.values(ANOMALY_TYPE);
export const ANOMALY_SEVERITIES: readonly AnomalySeverity[] = Object.values(ANOMALY_SEVERITY);

/** How the operator reads an anomaly: a fault to fix, or a chance to sell more. */
export const ALERT_CATEGORY = {
  Alert: "alert",
  Opportunity: "opportunity",
} as const;
export type AlertCategory = (typeof ALERT_CATEGORY)[keyof typeof ALERT_CATEGORY];

/** How far the agent run that handles an anomaly has got, in order. */
export const ALERT_STEP = {
  Detected: "detected",
  Investigating: "investigating",
  Planning: "planning",
  Guarding: "guarding",
  Acting: "acting",
  Verifying: "verifying",
} as const;
export type AlertStep = (typeof ALERT_STEP)[keyof typeof ALERT_STEP];
export const ALERT_STEPS: readonly AlertStep[] = Object.values(ALERT_STEP);
