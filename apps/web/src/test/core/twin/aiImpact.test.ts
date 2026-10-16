import { describe, expect, it } from "vitest";
import { impactOf, runVerify } from "@/core/twin/aiImpact";
import { BASELINE_CANDIDATE_ID, KPI_TREND } from "@/enums/simulation.enum";
import { demoAgentRun } from "@/fixtures/demo/agentRun";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { DEMO_SIMULATION_ID } from "@/fixtures/demo/simulation";

const candidates = demoCandidates();

describe("impactOf", () => {
  it("puts the baseline's KPIs next to the accepted candidate's, as served", () => {
    const impact = impactOf(candidates, DEMO_SIMULATION_ID, "cand-b")!;
    expect(impact.candidate_id).toBe("cand-b");
    expect(impact.evaluator_version).toBe("simulation-kpi-v1");
    expect(impact.rows.map((row) => [row.name, row.before.value, row.after.value, row.delta, row.trend])).toEqual([
      ["business_score", -0.05, 0.88, 0.93, KPI_TREND.Better],
      ["stockout_risk", 0.4, 0.15, -0.25, KPI_TREND.Better],
      ["service_level", 0.35, 0.75, 0.4, KPI_TREND.Better],
      ["movement_cost", 0, 0.12, 0.12, KPI_TREND.Worse],
      ["revenue_benefit", 0, 0.4, 0.4, KPI_TREND.Better],
      ["margin_benefit", 0, 0, 0, KPI_TREND.Same],
    ]);
    expect(impact.candidates.map((candidate) => candidate.candidate_id)).toEqual([BASELINE_CANDIDATE_ID, "cand-a", "cand-b", "cand-c"]);
  });

  it("is null without an accepted candidate", () => {
    expect(impactOf(candidates, DEMO_SIMULATION_ID, null)).toBeNull();
    expect(impactOf(candidates, DEMO_SIMULATION_ID, "cand-x")).toBeNull();
    expect(impactOf(candidates, DEMO_SIMULATION_ID, BASELINE_CANDIDATE_ID)).toBeNull();
    expect(impactOf(candidates, "sim-other", "cand-b")).toBeNull();
  });

  it("is null without a served baseline, never filling in a before value", () => {
    const noBaseline = candidates.filter((candidate) => candidate.candidate_id !== BASELINE_CANDIDATE_ID);
    expect(impactOf(noBaseline, DEMO_SIMULATION_ID, "cand-b")).toBeNull();
  });

  it("is null when the accepted candidate was not scored", () => {
    const unscored = candidates.map((candidate) => (candidate.candidate_id === "cand-b" ? { ...candidate, kpis: [] } : candidate));
    expect(impactOf(unscored, DEMO_SIMULATION_ID, "cand-b")).toBeNull();
  });
});

describe("runVerify", () => {
  it("is the VERIFY entry once a run naming the simulation has one, with the verifier's status", () => {
    const run = demoAgentRun();
    expect(runVerify(run, DEMO_SIMULATION_ID)?.status).toBe("INCONCLUSIVE");
    expect(runVerify(run.slice(0, 7), DEMO_SIMULATION_ID)).toBeNull();
    expect(runVerify(run, "sim-other")).toBeNull();
  });

  it("ignores a VERIFY of another run", () => {
    const ours = demoAgentRun("run-a").slice(0, 6);
    const other = demoAgentRun("run-b").map((entry) => ({ ...entry, simulation_id: undefined }));
    expect(runVerify([...ours, ...other], DEMO_SIMULATION_ID)).toBeNull();
  });
});
