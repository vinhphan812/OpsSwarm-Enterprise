import type { AnomalySeverity, AnomalyType } from "@/enums/anomaly.enum";

/**
 * One open anomaly, as apps/api serves it in `GET /anomalies` (`schemas.py` `Anomaly`).
 * `title`, `description` and `severity` come from the BE detector, never from the FE or an LLM.
 */
export type Anomaly = {
  anomaly_id: string;
  anomaly_type: AnomalyType;
  severity: AnomalySeverity;
  store_id: string;
  /** The product it is about; null for one about a whole shelf or the store. */
  sku: string | null;
  /** The shelf or piece of equipment it is about, when known. */
  shelf_id: string | null;
  title: string;
  description: string;
  /** ISO timestamp. */
  detected_at: string;
  /** Ids of the store events the detector read. */
  event_ids: string[];
  metadata: Record<string, string>;
  /**
   * Ties the anomaly to the agent run that handles it; the alert lifecycle follows that run.
   * TODO(BE #79): not served yet, so a real anomaly stays at "Detected" until it is.
   */
  correlation_id?: string;
  /** TODO(BE #79): not served yet. */
  slot_id?: string;
  /** Twin state the detector read, as `StoreResponse.context_version`. TODO(BE #79): not served yet. */
  context_version?: string;
};

/** `GET /anomalies`, as apps/api serves it (`schemas.py` `AnomaliesResponse`). */
export type AnomaliesResponse = {
  anomalies: Anomaly[];
  total: number;
  /** ISO timestamp the list starts from, when the request set one. */
  detected_since?: string | null;
};
