import { beforeEach, describe, expect, it } from "vitest";
import type { ActivityEntry } from "@/core/api/types";
import { useRunStore } from "@/state/run.store";

const trigger: ActivityEntry = {
  id: "act-1",
  ts: "2026-10-07T16:01:02Z",
  stage: "DETECT",
  summary: "Demand surge detected: P017",
};

describe("run store", () => {
  beforeEach(() => useRunStore.getState().reset());

  it("appends activity and tracks the latest stage", () => {
    useRunStore.getState().append(trigger);
    useRunStore.getState().append({ ...trigger, id: "act-2", stage: "INVESTIGATE" });

    const { activity, stage } = useRunStore.getState();
    expect(activity.map((entry) => entry.id)).toEqual(["act-1", "act-2"]);
    expect(stage).toBe("INVESTIGATE");
  });

  it("ignores a duplicate entry id", () => {
    useRunStore.getState().append(trigger);
    useRunStore.getState().append(trigger);

    expect(useRunStore.getState().activity).toHaveLength(1);
  });
});
