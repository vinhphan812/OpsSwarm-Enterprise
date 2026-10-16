import { describe, expect, test } from "vitest";
import { CONTROL_STAGES, groupRuns } from "@/core/agent/agentRuns";
import { STAGE_STATUS } from "@/enums/agent.enum";
import { demoAgentRun, DEMO_RUN_ID } from "@/fixtures/demo/agentRun";
import type { ActivityEntry, ControlStage } from "@/types/agent.type";

let seq = 0;
function entry(stage: ControlStage, correlation_id?: string, extra: Partial<ActivityEntry> = {}): ActivityEntry {
  seq += 1;
  return { id: `e${seq}`, ts: new Date(Date.UTC(2026, 9, 16, 8, 0, seq)).toISOString(), stage, summary: `${stage} ${seq}`, correlation_id, ...extra };
}

function statuses(entries: ActivityEntry[]) {
  return Object.fromEntries(groupRuns(entries).runs[0].stages.map(({ stage, status }) => [stage, status]));
}

describe("groupRuns", () => {
  test("puts the demo run in one card with all eight stages done", () => {
    const { runs, loose } = groupRuns(demoAgentRun());
    expect(loose).toEqual([]);
    expect(runs).toHaveLength(1);
    expect(runs[0].id).toBe(DEMO_RUN_ID);
    expect(runs[0].sku).toBe("P003");
    expect(runs[0].stages.map((stage) => stage.stage)).toEqual(CONTROL_STAGES);
    expect(runs[0].stages.every((stage) => stage.status === STAGE_STATUS.Done)).toBe(true);
    expect(runs[0].stages.every((stage) => stage.entries.length === 1)).toBe(true);
  });

  test("marks the stage the demo run is on as active while it plays", () => {
    const partial = demoAgentRun().slice(0, 3);
    expect(statuses(partial)).toEqual({
      OBSERVE: "done",
      DETECT: "done",
      INVESTIGATE: "active",
      PLAN: "pending",
      SIMULATE: "pending",
      GUARD: "pending",
      ACT: "pending",
      VERIFY: "pending",
    });
  });

  test("leaves ACT and VERIFY pending for a run that stops at GUARD", () => {
    const run = (["OBSERVE", "DETECT", "INVESTIGATE", "PLAN", "SIMULATE", "GUARD"] as const).map((stage) => entry(stage, "r1"));
    const result = statuses(run);
    expect(result.GUARD).toBe(STAGE_STATUS.Active);
    expect(result.SIMULATE).toBe(STAGE_STATUS.Done);
    expect(result.ACT).toBe(STAGE_STATUS.Pending);
    expect(result.VERIFY).toBe(STAGE_STATUS.Pending);
  });

  test("never fills in a stage the run skipped", () => {
    const result = statuses([entry("DETECT", "r1"), entry("ACT", "r1"), entry("VERIFY", "r1")]);
    expect(result).toMatchObject({ OBSERVE: "pending", DETECT: "done", PLAN: "pending", GUARD: "pending", ACT: "done", VERIFY: "done" });
  });

  test("keeps every entry of a stage the run went back to", () => {
    const run = [entry("SIMULATE", "r1"), entry("GUARD", "r1"), entry("SIMULATE", "r1")];
    const { stages } = groupRuns(run).runs[0];
    const simulate = stages.find((stage) => stage.stage === "SIMULATE")!;
    expect(simulate.entries.map((e) => e.id)).toEqual([run[0].id, run[2].id]);
    expect(simulate.status).toBe(STAGE_STATUS.Active);
    expect(stages.find((stage) => stage.stage === "GUARD")!.status).toBe(STAGE_STATUS.Done);
  });

  test("orders runs by their latest entry, newest first, and keeps entries of no run apart", () => {
    const a1 = entry("OBSERVE", "a");
    const b1 = entry("OBSERVE", "b");
    const loose = entry("OBSERVE");
    const a2 = entry("DETECT", "a");
    const { runs, loose: rest } = groupRuns([a1, b1, loose, a2]);
    expect(runs.map((run) => run.id)).toEqual(["a", "b"]);
    expect(runs[0].entries).toEqual([a1, a2]);
    expect(rest).toEqual([loose]);
  });

  test("returns nothing for an empty timeline", () => {
    expect(groupRuns([])).toEqual({ runs: [], loose: [] });
  });
});
