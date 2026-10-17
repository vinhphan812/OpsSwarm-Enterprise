/**
 * The chance that one product runs out on the shelf within the forecast horizon, as the
 * forecasting service scores it. TODO(BE): apps/api serves no stockout risk yet (the
 * agents' `get_stockout_risk` tool is not exposed over HTTP); this shape is the FE's
 * proposal, e.g. `GET /stockout-risk` returning a list of these. Until then only
 * `?twin=demo` has it (`fixtures/demo/stockoutRisk.ts`).
 */
export type StockoutRisk = {
  store_id: string;
  sku: string;
  /** Probability from 0 to 1 that the shelf runs out within `horizon_hours`. */
  risk: number;
  horizon_hours: number;
  /** The twin state the risk was scored on, as `StoreResponse.context_version`. */
  context_version: string;
};
