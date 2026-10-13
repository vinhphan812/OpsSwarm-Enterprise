import { describe, expect, it } from "vitest";
import { AGENT_FOCUS_IDLE_MS } from "@/constants/camera.constant";
import { agentFocusOf, agentFocusWait } from "@/core/agent/agentFocus";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import type { ActivityEntry } from "@/types/agent.type";

const entry: ActivityEntry = {
  id: "e1",
  ts: "2026-10-13T08:00:00Z",
  stage: "INVESTIGATE",
  summary: "Checking P003.",
};

describe("agentFocusOf", () => {
  it("focuses the product of a focusable stage, with its summary as the reason", () => {
    expect(agentFocusOf({ ...entry, sku: "P003", shelf_id: "A01" })).toEqual({
      entityId: "P003",
      entityType: ENTITY_TYPE.Product,
      reason: "Checking P003.",
    });
  });

  it("focuses the fixture when there is no SKU", () => {
    expect(agentFocusOf({ ...entry, stage: "VERIFY", shelf_id: "A01" })).toMatchObject({
      entityId: "A01",
      entityType: ENTITY_TYPE.Shelf,
    });
    expect(agentFocusOf({ ...entry, stage: "ACT", shelf_id: "GDC01" })).toMatchObject({
      entityId: "GDC01",
      entityType: ENTITY_TYPE.Equipment,
    });
  });

  it("does not move the camera for other stages or an entry without a target", () => {
    expect(agentFocusOf({ ...entry, stage: "DETECT", sku: "P003" })).toBeNull();
    expect(agentFocusOf({ ...entry, stage: "PLAN", sku: "P003" })).toBeNull();
    expect(agentFocusOf(entry)).toBeNull();
  });
});

describe("agentFocusWait", () => {
  const NOW = Date.parse("2026-10-13T08:00:00Z");

  it("waits while the user drags and for the idle time after they last used the camera", () => {
    expect(agentFocusWait({ userDragging: true, userActiveAt: 0 }, 99_999)).toBe(AGENT_FOCUS_IDLE_MS);
    expect(agentFocusWait({ userDragging: false, userActiveAt: 10_000 }, 11_000)).toBe(AGENT_FOCUS_IDLE_MS - 1000);
    expect(agentFocusWait({ userDragging: false, userActiveAt: 10_000 }, 10_000 + AGENT_FOCUS_IDLE_MS)).toBe(0);
    expect(agentFocusWait({ userDragging: false, userActiveAt: 0 }, NOW)).toBe(0);
  });
});
