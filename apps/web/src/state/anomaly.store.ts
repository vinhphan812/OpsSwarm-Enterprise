import { create } from "zustand";
import { ANOMALY_SEVERITIES, type AnomalySeverity } from "@/enums/anomaly.enum";
import type { AnomaliesResponse, Anomaly } from "@/types/anomaly.type";

type AnomalyStore = {
  /** Open anomalies, as the anomaly API last served them. */
  anomalies: Anomaly[];
  /** Why the last read of the anomalies failed; null once a read succeeds. `anomalies` keeps the last list. */
  readError: string | null;
  /** Replaces every open anomaly with a fresh `GET /anomalies` response, and clears `readError`. */
  setAll: (response: AnomaliesResponse) => void;
  /** A read of the anomalies failed: keeps the last list and says why. */
  fail: (message: string) => void;
  /** An anomaly event: adds the anomaly, or replaces the one with the same id. */
  raise: (anomaly: Anomaly) => void;
  /** The anomaly was handled and is no longer open. */
  resolve: (anomalyId: string) => void;
};

/**
 * Read-side copy of the open anomalies. Never the source of truth.
 * TODO(#95): fill this from `GET /anomalies` (`setAll`, and `fail` when a read fails).
 * Until then only `?twin=demo` and tests fill it.
 */
export const useAnomalyStore = create<AnomalyStore>()((set) => ({
  anomalies: [],
  readError: null,
  setAll: (response) => set({ anomalies: response.anomalies, readError: null }),
  fail: (readError) => set({ readError }),
  raise: (anomaly) =>
    set((state) => ({
      anomalies: [...state.anomalies.filter((open) => open.anomaly_id !== anomaly.anomaly_id), anomaly],
    })),
  resolve: (anomalyId) =>
    set((state) => ({ anomalies: state.anomalies.filter((open) => open.anomaly_id !== anomalyId) })),
}));

/** Open anomalies on one product, oldest first. One about a whole shelf (no SKU) is on none. */
export function anomaliesOf(anomalies: Anomaly[], sku: string) {
  return anomalies.filter((anomaly) => anomaly.sku === sku);
}

/** Each product with open anomalies and the worst severity among them. Shelf-wide ones have no product halo. */
export function worstSeverities(anomalies: Anomaly[]): Map<string, AnomalySeverity> {
  const rank = (severity: AnomalySeverity) => ANOMALY_SEVERITIES.indexOf(severity);
  const worst = new Map<string, AnomalySeverity>();
  for (const { sku, severity } of anomalies) {
    if (!sku) continue;
    const current = worst.get(sku);
    if (!current || rank(severity) > rank(current)) worst.set(sku, severity);
  }
  return worst;
}
