import { ANOMALY_SEVERITY, ANOMALY_TYPE, type AnomalySeverity, type AnomalyType } from "@/enums/anomaly.enum";
import type { AnomaliesResponse, Anomaly } from "@/types/anomaly.type";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import { demoStoreState } from "./store";

/**
 * Demo data for `?twin=demo` (development builds only), never Live Twin truth.
 * Open anomalies on the demo store, in the `GET /anomalies` shape apps/api serves. Titles
 * and descriptions are written from the shelf figures by fixed templates, as a detector
 * would, never by a model. Stock anomalies agree with the shelf figures. P001 has none, so
 * one can be raised on it. `correlation_id`, `slot_id` and `context_version` are filled
 * although apps/api does not serve them yet (#79), so the demo shows a full lifecycle.
 */

const DETECTED_AT = "2026-10-09T08:00:00Z";

/** The agent run that handles the anomaly of `type` on `subject` (a SKU or shelf): one run per anomaly. */
export function demoCorrelationId(subject: string, type: AnomalyType) {
  return `run-${subject}-${type}`;
}

/** Title and description of an anomaly of `type` on `product`, from its figures. */
function describeAnomaly(product: ProductInventory, type: AnomalyType): Pick<Anomaly, "title" | "description"> {
  const { sku, slot_id, shelf_quantity: shelf, backroom_quantity: backroom, facings } = product;
  const figures = `${shelf} on the shelf, ${backroom} in the backroom, ${facings} facings.`;
  switch (type) {
    case ANOMALY_TYPE.Stockout:
      return { title: `${sku} is out of stock on ${slot_id}`, description: figures };
    case ANOMALY_TYPE.DemandSurge:
      return { title: `Demand for ${sku} is above forecast`, description: `Sales above forecast. ${figures}` };
    case ANOMALY_TYPE.SlowMoving:
      return { title: `${sku} sells below forecast`, description: `Sales below forecast. ${figures}` };
    case ANOMALY_TYPE.ExcessInventory:
      return { title: `Too much ${sku} in stock`, description: `More stock than it sells. ${figures}` };
    case ANOMALY_TYPE.PriceAnomaly:
      return { title: `Price of ${sku} does not match`, description: `The price charged differs from the expected one.` };
    case ANOMALY_TYPE.ShelfViolation:
      return { title: `${sku} breaks the planogram on ${slot_id}`, description: figures };
  }
}

/** An anomaly on `product`, read from the twin state at `contextVersion`. */
export function anomalyFor(
  product: ProductInventory,
  type: AnomalyType,
  severity: AnomalySeverity,
  contextVersion: string,
  detectedAt: string = DETECTED_AT,
): Anomaly {
  return {
    anomaly_id: `anm-${product.sku}-${type}`,
    anomaly_type: type,
    severity,
    store_id: product.store_id,
    sku: product.sku,
    shelf_id: product.shelf_id,
    ...describeAnomaly(product, type),
    detected_at: detectedAt,
    event_ids: [],
    metadata: {},
    correlation_id: demoCorrelationId(product.sku, type),
    slot_id: product.slot_id,
    context_version: contextVersion,
  };
}

/** A planogram anomaly on a whole shelf, with no product: the kind apps/api serves with `sku: null`. */
export function shelfAnomalyFor(storeId: string, shelfId: string, severity: AnomalySeverity, contextVersion: string): Anomaly {
  const type = ANOMALY_TYPE.ShelfViolation;
  return {
    anomaly_id: `anm-${shelfId}-${type}`,
    anomaly_type: type,
    severity,
    store_id: storeId,
    sku: null,
    shelf_id: shelfId,
    title: `Shelf ${shelfId} breaks its planogram`,
    description: `Products on ${shelfId} do not match their planned slots.`,
    detected_at: DETECTED_AT,
    event_ids: [],
    metadata: {},
    correlation_id: demoCorrelationId(shelfId, type),
    context_version: contextVersion,
  };
}

const ANOMALIES: [sku: string, type: AnomalyType, severity: AnomalySeverity][] = [
  ["P003", ANOMALY_TYPE.Stockout, ANOMALY_SEVERITY.High],
  ["P010", ANOMALY_TYPE.Stockout, ANOMALY_SEVERITY.High],
  // Shelves full but not selling, so their halos show at every severity.
  ["P002", ANOMALY_TYPE.PriceAnomaly, ANOMALY_SEVERITY.Critical],
  ["P006", ANOMALY_TYPE.SlowMoving, ANOMALY_SEVERITY.High],
  ["P009", ANOMALY_TYPE.SlowMoving, ANOMALY_SEVERITY.Medium],
  ["P012", ANOMALY_TYPE.SlowMoving, ANOMALY_SEVERITY.Low],
  ["P011", ANOMALY_TYPE.ExcessInventory, ANOMALY_SEVERITY.Low],
  // Selling faster than forecast with stock to spare: an opportunity rather than an alert.
  ["P008", ANOMALY_TYPE.DemandSurge, ANOMALY_SEVERITY.Medium],
];

/** A shelf-wide anomaly: picking it focuses the shelf, as it names no product. */
const SHELF_ANOMALY = { shelfId: "A02", severity: ANOMALY_SEVERITY.Medium };

/** Open anomalies of `state`; a product that left the state takes its anomaly with it. */
export function demoAnomalies(state: StoreResponse = demoStoreState()): AnomaliesResponse {
  const bySku = new Map(state.products.map((product) => [product.sku, product]));
  const anomalies = ANOMALIES.flatMap(([sku, type, severity]) => {
    const product = bySku.get(sku);
    return product ? [anomalyFor(product, type, severity, state.context_version)] : [];
  });
  anomalies.push(shelfAnomalyFor(state.store_id, SHELF_ANOMALY.shelfId, SHELF_ANOMALY.severity, state.context_version));
  return { anomalies, total: anomalies.length, detected_since: null };
}
