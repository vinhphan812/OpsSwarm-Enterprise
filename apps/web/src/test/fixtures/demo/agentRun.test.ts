import { afterEach, describe, expect, it, vi } from "vitest";
import { agentFocusOf } from "@/core/agent/agentFocus";
import { DEMO_AGENT_STEP_MS, demoAgentRun, replayDemoAgentRun } from "@/fixtures/demo/agentRun";
import { demoStoreState } from "@/fixtures/demo/store";
import { useRunStore } from "@/state/run.store";

afterEach(() => vi.useRealTimers());

describe("demo agent run", () => {
  it("goes through the whole control loop, OBSERVE to VERIFY", () => {
    expect(demoAgentRun().map((entry) => entry.stage)).toEqual([
      "OBSERVE",
      "DETECT",
      "INVESTIGATE",
      "PLAN",
      "SIMULATE",
      "GUARD",
      "ACT",
      "VERIFY",
    ]);
  });

  it("focuses a product and a shelf that are in the demo store", () => {
    const products = demoStoreState().products;
    const focuses = demoAgentRun().map(agentFocusOf).filter((focus) => focus !== null);
    expect(focuses.map((focus) => `${focus.entityType}:${focus.entityId}`)).toEqual([
      "product:P003",
      "product:P003",
      "shelf:A01",
    ]);
    expect(products.find((product) => product.sku === "P003")).toMatchObject({ shelf_id: "A01", slot_id: "A01-S21" });
  });

  it("replays into the timeline step by step, and can be stopped", () => {
    vi.useFakeTimers();
    useRunStore.getState().append({ id: "old", ts: "2026-10-13T08:00:00Z", stage: "OBSERVE", summary: "old" });
    const stop = replayDemoAgentRun();
    vi.advanceTimersByTime(0);
    expect(useRunStore.getState().activity.map((entry) => entry.stage)).toEqual(["OBSERVE"]);
    vi.advanceTimersByTime(DEMO_AGENT_STEP_MS * 2);
    expect(useRunStore.getState().stage).toBe("INVESTIGATE");
    stop();
    vi.advanceTimersByTime(DEMO_AGENT_STEP_MS * 10);
    expect(useRunStore.getState().activity).toHaveLength(3);
  });
});
