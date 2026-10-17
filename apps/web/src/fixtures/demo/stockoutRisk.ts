import { demoStoreState } from "./store";
import type { StockoutRisk } from "@/types/stockoutRisk.type";

/**
 * Demo data for `?twin=demo` (development builds only), never Live Twin truth.
 * Stockout risk per product in the proposed shape (`StockoutRisk`), as a forecast would
 * score the demo store: the two products out of stock with an open stockout alert (P003,
 * P010) are red, the low ones orange or yellow, the rest green. Filler stock is never low
 * (`store.ts`), so it is green too.
 */

const HORIZON_HOURS = 24;

/** The named products' risk; any other product of the demo store gets `FILLER_RISK`. */
const NAMED_RISK: Record<string, number> = {
  P001: 0.03,
  P002: 0.04,
  P003: 0.92,
  P004: 0.24,
  P005: 0.02,
  P006: 0.01,
  P007: 0.38,
  P008: 0.12,
  P009: 0.03,
  P010: 0.87,
  P011: 0.01,
  P012: 0.02,
  P013: 0.06,
  P014: 0.04,
  P015: 0.18,
  P016: 0.03,
  P018: 0.02,
  P020: 0.04,
};
const FILLER_RISK = 0.02;

/** The demo store's stockout risk, one per product. A new array per call. */
export function demoStockoutRisk(): StockoutRisk[] {
  const store = demoStoreState();
  return store.products.map(({ sku }) => ({
    store_id: store.store_id,
    sku,
    risk: NAMED_RISK[sku] ?? FILLER_RISK,
    horizon_hours: HORIZON_HOURS,
    context_version: store.context_version,
  }));
}
