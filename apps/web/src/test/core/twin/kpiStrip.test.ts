import { describe, expect, it } from "vitest";
import { REVENUE_TODAY_STALE_MS } from "@/constants/app.constant";
import { KPI_MISSING, onShelfAvailability, projectedImpact, revenueToday, stockoutRisk } from "@/core/twin/kpiStrip";
import { ANOMALY_TYPE } from "@/enums/anomaly.enum";
import { BASELINE_CANDIDATE_ID } from "@/enums/simulation.enum";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoRevenue } from "@/fixtures/demo/commerce";
import { demoStoreState } from "@/fixtures/demo/store";
import { REVENUE_PERIOD } from "@/enums/commerce.enum";

const live = demoStoreState();

describe("revenueToday", () => {
  it("is the served revenue, and missing until the route answers", () => {
    const summary = demoRevenue(REVENUE_PERIOD.Today);
    expect(revenueToday({ value: summary, readAt: 1_000 }, 1_000)).toEqual({ value: summary.revenue });
    expect(revenueToday(null, 1_000)).toEqual({ value: null, reason: KPI_MISSING.NotServed });
  });

  it("is missing, never the old figure, once the last good read is stale", () => {
    const read = { value: demoRevenue(REVENUE_PERIOD.Today), readAt: 1_000 };
    expect(revenueToday(read, 1_000 + REVENUE_TODAY_STALE_MS)).toEqual({ value: read.value.revenue });
    expect(revenueToday(read, 1_001 + REVENUE_TODAY_STALE_MS)).toEqual({ value: null, reason: KPI_MISSING.Stale });
  });
});

describe("onShelfAvailability", () => {
  it("counts the served products with stock on the shelf", () => {
    const { value } = onShelfAvailability(live);
    const out = live.products.filter((product) => product.shelf_quantity <= 0).length;
    expect(value).toEqual({ onShelf: live.products.length - out, total: live.products.length, share: (live.products.length - out) / live.products.length });
  });

  it("is missing without a Live Twin or without products, never 0%", () => {
    expect(onShelfAvailability(null)).toEqual({ value: null, reason: KPI_MISSING.NotServed });
    expect(onShelfAvailability({ ...live, products: [] })).toEqual({ value: null, reason: KPI_MISSING.Empty });
  });
});

describe("stockoutRisk", () => {
  it("counts products with an open stockout in the feed", () => {
    const { anomalies } = demoAnomalies(live);
    const expected = new Set(anomalies.filter((anomaly) => anomaly.anomaly_type === ANOMALY_TYPE.Stockout).map((anomaly) => anomaly.sku)).size;
    expect(expected).toBeGreaterThan(0);
    expect(stockoutRisk(anomalies, true)).toEqual({ value: expected });
    expect(stockoutRisk([], true)).toEqual({ value: 0 });
  });

  it("is missing until the feed is served, never 0", () => {
    expect(stockoutRisk([], false)).toEqual({ value: null, reason: KPI_MISSING.NotServed });
  });
});

describe("projectedImpact", () => {
  const candidates = demoCandidates(live);

  it("is the top-scored candidate's business score over the baseline while none is selected", () => {
    expect(projectedImpact(candidates, true, null)).toEqual({
      value: { candidateId: "cand-b", delta: 0.93, evaluatorVersion: "simulation-kpi-v1" },
    });
  });

  it("follows the selected candidate", () => {
    expect(projectedImpact(candidates, true, "cand-c").value).toMatchObject({ candidateId: "cand-c", delta: -0.1 });
  });

  it("is missing without a simulation, a baseline or a scored plan", () => {
    expect(projectedImpact(candidates, false, null)).toEqual({ value: null, reason: KPI_MISSING.NoSimulation });
    expect(projectedImpact([], true, null)).toEqual({ value: null, reason: KPI_MISSING.NotScored });
    const noBaseline = candidates.filter((candidate) => candidate.candidate_id !== BASELINE_CANDIDATE_ID);
    expect(projectedImpact(noBaseline, true, "cand-b")).toEqual({ value: null, reason: KPI_MISSING.NotScored });
  });
});
