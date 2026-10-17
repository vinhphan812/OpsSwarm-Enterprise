import { describe, expect, it } from "vitest";
import { riskBandsBySku, stockoutRiskBand } from "@/core/twin/stockoutRisk";
import { ANOMALY_TYPE } from "@/enums/anomaly.enum";
import { RISK_BAND } from "@/enums/ui.enum";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { demoStockoutRisk } from "@/fixtures/demo/stockoutRisk";
import { demoStoreState } from "@/fixtures/demo/store";
import type { StockoutRisk } from "@/types/stockoutRisk.type";

describe("stockoutRiskBand", () => {
  it("is green under 5%, yellow 5–15%, orange 15–30%, red over 30%", () => {
    expect(stockoutRiskBand(0)).toBe(RISK_BAND.Low);
    expect(stockoutRiskBand(0.049)).toBe(RISK_BAND.Low);
    expect(stockoutRiskBand(0.05)).toBe(RISK_BAND.Elevated);
    expect(stockoutRiskBand(0.149)).toBe(RISK_BAND.Elevated);
    expect(stockoutRiskBand(0.15)).toBe(RISK_BAND.High);
    expect(stockoutRiskBand(0.3)).toBe(RISK_BAND.High);
    expect(stockoutRiskBand(0.301)).toBe(RISK_BAND.Severe);
    expect(stockoutRiskBand(1)).toBe(RISK_BAND.Severe);
  });

  it("gives no band to a value that is not a probability, so the slot stays neutral", () => {
    for (const risk of [-0.01, 1.01, Number.NaN, Number.POSITIVE_INFINITY]) expect(stockoutRiskBand(risk)).toBeNull();
  });
});

describe("riskBandsBySku", () => {
  const risk = (sku: string, value: number): StockoutRisk => ({
    store_id: "store-001",
    sku,
    risk: value,
    horizon_hours: 24,
    context_version: "store-001:v1",
  });

  it("bands each served SKU and leaves out one whose risk is not a probability", () => {
    const bands = riskBandsBySku([risk("P001", 0.02), risk("P003", 0.9), risk("P009", Number.NaN)]);
    expect([...bands]).toEqual([
      ["P001", RISK_BAND.Low],
      ["P003", RISK_BAND.Severe],
    ]);
  });
});

describe("demoStockoutRisk", () => {
  const bands = riskBandsBySku(demoStockoutRisk());

  it("has a risk for every product of the demo store, scored on its state", () => {
    const store = demoStoreState();
    expect(bands.size).toBe(store.products.length);
    expect(demoStockoutRisk().every((item) => item.context_version === store.context_version)).toBe(true);
  });

  it("puts each SKU with an open stockout alert in the orange or red band", () => {
    const stockouts = demoAnomalies().anomalies.filter((anomaly) => anomaly.anomaly_type === ANOMALY_TYPE.Stockout);
    expect(stockouts.map((anomaly) => anomaly.sku)).toEqual(["P003", "P010"]);
    for (const { sku } of stockouts) expect([RISK_BAND.High, RISK_BAND.Severe]).toContain(bands.get(sku!));
  });

  it("uses every band, so the legend's colours all show on the demo", () => {
    expect(new Set(bands.values())).toEqual(new Set(Object.values(RISK_BAND)));
  });
});
