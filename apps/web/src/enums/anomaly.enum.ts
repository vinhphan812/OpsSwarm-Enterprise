/** What the detector found wrong with a product. TODO(BE): agree the values with the anomaly API. */
export const ANOMALY_KIND = {
  /** Nothing left on the shelf. */
  Stockout: "stockout",
  /** Fewer units on the shelf than facings to fill. */
  LowStock: "low_stock",
  /** Sales fell below forecast; seen in POS data, not in shelf figures. */
  SalesDrop: "sales_drop",
} as const;
export type AnomalyKind = (typeof ANOMALY_KIND)[keyof typeof ANOMALY_KIND];

export const ANOMALY_SEVERITY = {
  Low: "low",
  Medium: "medium",
  High: "high",
} as const;
export type AnomalySeverity = (typeof ANOMALY_SEVERITY)[keyof typeof ANOMALY_SEVERITY];
export const ANOMALY_KINDS: readonly AnomalyKind[] = Object.values(ANOMALY_KIND);
export const ANOMALY_SEVERITIES: readonly AnomalySeverity[] = Object.values(ANOMALY_SEVERITY);
