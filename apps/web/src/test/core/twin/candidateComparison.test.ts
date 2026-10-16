import { describe, expect, it } from "vitest";
import { compareCandidates, kpiDelta, kpiTrend, planLetter } from "@/core/twin/candidateComparison";
import { demoStoreState } from "@/fixtures/demo/store";
import { BASELINE_CANDIDATE_ID, KPI_NAME, KPI_TREND } from "@/enums/simulation.enum";
import type { Candidate, CandidateKPI } from "@/types/simulation.type";

const state = demoStoreState();

const kpi = (name: string, value: number): CandidateKPI => ({ name, value, unit: "share", source: "simulation-kpi-v1" });

function candidate(id: string, kpis: CandidateKPI[]): Candidate {
  return {
    candidate_id: id,
    simulation_id: "sim-1",
    proposed_actions: [],
    state,
    kpis,
    evaluator_version: "simulation-kpi-v1",
    provenance: "test",
  };
}

const baseline = candidate(BASELINE_CANDIDATE_ID, [kpi(KPI_NAME.StockoutRisk, 0.15), kpi(KPI_NAME.ServiceLevel, 0.11), kpi(KPI_NAME.BusinessScore, -0.04)]);
const a = candidate("A", [kpi(KPI_NAME.StockoutRisk, 0.15), kpi(KPI_NAME.ServiceLevel, 0.27), kpi(KPI_NAME.BusinessScore, 0.12)]);
const b = candidate("B", [kpi(KPI_NAME.ServiceLevel, 0.27), kpi(KPI_NAME.MovementCost, 0.03), kpi(KPI_NAME.BusinessScore, 0.09)]);

describe("kpiDelta", () => {
  it("keeps the served precision", () => {
    expect(kpiDelta(0.27, 0.11)).toBe(0.16);
    expect(kpiDelta(0.12, -0.04)).toBe(0.16);
    expect(kpiDelta(0.15, 0.15)).toBe(0);
    expect(kpiDelta(1240.5, 380.25)).toBe(860.25);
  });
});

describe("kpiTrend", () => {
  it("reads lower stockout risk and movement cost as better", () => {
    expect(kpiTrend(KPI_NAME.StockoutRisk, -0.1)).toBe(KPI_TREND.Better);
    expect(kpiTrend(KPI_NAME.MovementCost, 0.1)).toBe(KPI_TREND.Worse);
  });

  it("reads a higher value of any other KPI as better", () => {
    expect(kpiTrend(KPI_NAME.ServiceLevel, 0.16)).toBe(KPI_TREND.Better);
    expect(kpiTrend("unknown_kpi", -1)).toBe(KPI_TREND.Worse);
    expect(kpiTrend(KPI_NAME.BusinessScore, 0)).toBe(KPI_TREND.Same);
  });
});

describe("compareCandidates", () => {
  it("splits the baseline from the proposals, in served order", () => {
    const comparison = compareCandidates([a, baseline, b]);
    expect(comparison.baseline).toBe(baseline);
    expect(comparison.proposals.map((item) => item.candidate_id)).toEqual(["A", "B"]);
  });

  it("lists every KPI once, the business score first and the rest in the order first served, with the exact served values", () => {
    const { rows } = compareCandidates([baseline, a, b]);
    expect(rows.map((row) => row.name)).toEqual([KPI_NAME.BusinessScore, KPI_NAME.StockoutRisk, KPI_NAME.ServiceLevel, KPI_NAME.MovementCost]);
    const service = rows.find((row) => row.name === KPI_NAME.ServiceLevel)!;
    expect(service.baseline).toBe(baseline.kpis[1]);
    expect(service.cells.A?.kpi).toBe(a.kpis[1]);
    expect(service.cells.A).toMatchObject({ delta: 0.16, trend: KPI_TREND.Better });
  });

  it("leaves no cell for a KPI a candidate lacks, and no delta without a baseline value", () => {
    const { rows } = compareCandidates([baseline, a, b]);
    expect(rows.find((row) => row.name === KPI_NAME.StockoutRisk)!.cells.B).toBeUndefined();
    const movement = rows.find((row) => row.name === KPI_NAME.MovementCost)!;
    expect(movement.baseline).toBeNull();
    expect(movement.cells.B).toMatchObject({ delta: null, trend: null });
  });

  it("gives no baseline and no deltas when none is served", () => {
    const comparison = compareCandidates([a, b]);
    expect(comparison.baseline).toBeNull();
    expect(comparison.rows.every((row) => Object.values(row.cells).every((cell) => cell?.delta === null))).toBe(true);
  });

  it("marks the proposal with the highest business score, never the baseline", () => {
    const high = candidate("high-baseline", []);
    expect(compareCandidates([baseline, a, b, high]).topScoreId).toBe("A");
  });

  it("takes the recommended plan only from the served flag, never from the scores", () => {
    expect(compareCandidates([baseline, a, b]).recommendedId).toBeNull();
    expect(compareCandidates([baseline, a, { ...b, recommended: true }]).recommendedId).toBe("B");
    // The baseline is never a plan to recommend.
    expect(compareCandidates([{ ...baseline, recommended: true }, a]).recommendedId).toBeNull();
  });

  it("labels the plans A, B, C in served order", () => {
    expect([0, 1, 2].map(planLetter)).toEqual(["A", "B", "C"]);
  });

  it("marks no top score on a tie or when nothing is scored", () => {
    const twin = candidate("A2", [kpi(KPI_NAME.BusinessScore, 0.12)]);
    expect(compareCandidates([a, twin]).topScoreId).toBeNull();
    expect(compareCandidates([candidate("X", []), candidate("Y", [])]).topScoreId).toBeNull();
    expect(compareCandidates([]).rows).toEqual([]);
  });
});
