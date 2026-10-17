import { RISK_BAND, type RiskBand } from "@/enums/ui.enum";
import type { StockoutRisk } from "@/types/stockoutRisk.type";

/**
 * Upper bounds of the stockout-risk bands, as shares (#213): green under 5%, yellow 5–15%,
 * orange 15–30%, red above 30%. A risk on a bound takes the higher band, except 30%, which
 * is still orange: red is only "above 30%".
 */
export const RISK_BAND_BOUNDS = { low: 0.05, elevated: 0.15, high: 0.3 } as const;

/** The band of a served risk, or null for a value that is not a probability (no data). */
export function stockoutRiskBand(risk: number): RiskBand | null {
  if (!Number.isFinite(risk) || risk < 0 || risk > 1) return null;
  if (risk < RISK_BAND_BOUNDS.low) return RISK_BAND.Low;
  if (risk < RISK_BAND_BOUNDS.elevated) return RISK_BAND.Elevated;
  if (risk <= RISK_BAND_BOUNDS.high) return RISK_BAND.High;
  return RISK_BAND.Severe;
}

/** The band of each SKU with a served risk; a SKU missing here has no data and stays neutral. */
export function riskBandsBySku(risks: readonly StockoutRisk[]): Map<string, RiskBand> {
  const bands = new Map<string, RiskBand>();
  for (const { sku, risk } of risks) {
    const band = stockoutRiskBand(risk);
    if (band) bands.set(sku, band);
  }
  return bands;
}
