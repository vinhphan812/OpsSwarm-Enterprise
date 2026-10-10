import { ANOMALY_KIND, ANOMALY_SEVERITY, type AnomalyKind, type AnomalySeverity } from "@/enums/anomaly.enum";
import type { AnomaliesResponse, Anomaly } from "@/types/anomaly.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { demoStoreState } from "./store";

/**
 * Demo data for `?twin=demo` (development builds only), never Live Twin truth.
 * Open anomalies on the demo store, in the proposed `AnomaliesResponse` shape. Stock
 * anomalies agree with the shelf figures. P001 has none, so one can be raised on it.
 */

const DETECTED_AT = "2026-10-09T08:00:00Z";
const CORRELATION_ID = "run-20261009-001";

/** An anomaly on `product`, read from the twin state at `contextVersion`. */
export function anomalyFor(
  product: ProductInventory,
  kind: AnomalyKind,
  severity: AnomalySeverity,
  contextVersion: string,
  detectedAt: string = DETECTED_AT,
): Anomaly {
  return {
    anomaly_id: `anm-${product.sku}-${kind}`,
    store_id: product.store_id,
    sku: product.sku,
    shelf_id: product.shelf_id,
    slot_id: product.slot_id,
    kind,
    severity,
    detected_at: detectedAt,
    context_version: contextVersion,
    correlation_id: CORRELATION_ID,
  };
}

const ANOMALIES: [sku: string, kind: AnomalyKind, severity: AnomalySeverity][] = [
  ["P003", ANOMALY_KIND.Stockout, ANOMALY_SEVERITY.High],
  ["P004", ANOMALY_KIND.LowStock, ANOMALY_SEVERITY.Medium],
  // Low on the shelf with nothing in the backroom to refill it.
  ["P007", ANOMALY_KIND.LowStock, ANOMALY_SEVERITY.High],
  ["P010", ANOMALY_KIND.Stockout, ANOMALY_SEVERITY.High],
  ["P012", ANOMALY_KIND.SalesDrop, ANOMALY_SEVERITY.Low],
  // Shelves full but not selling, so their halos show at every severity.
  ["P009", ANOMALY_KIND.SalesDrop, ANOMALY_SEVERITY.Medium],
  ["P006", ANOMALY_KIND.SalesDrop, ANOMALY_SEVERITY.High],
];

/** Open anomalies of `state`; a product that left the state takes its anomaly with it. */
export function demoAnomalies(state: StoreResponse = demoStoreState()): AnomaliesResponse {
  const bySku = new Map(state.products.map((product) => [product.sku, product]));
  const anomalies = ANOMALIES.flatMap(([sku, kind, severity]) => {
    const product = bySku.get(sku);
    return product ? [anomalyFor(product, kind, severity, state.context_version)] : [];
  });
  return { store_id: state.store_id, context_version: state.context_version, anomalies };
}
