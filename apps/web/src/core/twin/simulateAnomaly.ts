import type { AnomalySeverity, AnomalyType } from "@/enums/anomaly.enum";
import { anomalyFor } from "@/fixtures/demo/anomalies";
import { useAnomalyStore } from "@/state/anomaly.store";
import type { ProductInventory } from "@/types/twin.type";

/**
 * Raising anomalies by hand from the browser console (`twin.raise()`, `twin.resolve()`
 * under `?twin=memory|demo`), to check the highlight before the detector serves any.
 * Development builds only; in production an anomaly only ever comes from the anomaly API.
 */

/** Raises an anomaly event on `product`, as read from the twin state at `contextVersion`. Returns its id. */
export function simulateAnomaly(
  product: ProductInventory,
  type: AnomalyType,
  severity: AnomalySeverity,
  contextVersion: string,
): string {
  const anomaly = anomalyFor(product, type, severity, contextVersion, new Date().toISOString());
  useAnomalyStore.getState().raise(anomaly);
  return anomaly.anomaly_id;
}

/** Closes every open anomaly on `sku`. */
export function resolveAnomalies(sku: string) {
  const { anomalies, resolve } = useAnomalyStore.getState();
  anomalies.filter((anomaly) => anomaly.sku === sku).forEach((anomaly) => resolve(anomaly.anomaly_id));
}
