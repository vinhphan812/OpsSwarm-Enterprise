// @vitest-environment jsdom
import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentFocusCaption } from "@/components/twin/AgentFocusCaption";
import { AGENT_FOCUS_IDLE_MS } from "@/constants/camera.constant";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { FOCUS_SOURCE } from "@/enums/ui.enum";
import { useAgentFocus } from "@/hooks/agentFocus.hook";
import { useRunStore } from "@/state/run.store";
import { useUiStore } from "@/state/ui.store";
import type { ActivityEntry } from "@/types/agent.type";

MotionGlobalConfig.skipAnimations = true;

const NOW = Date.parse("2026-10-13T08:00:00Z");

const verify: ActivityEntry = {
  id: "v1",
  ts: "2026-10-13T08:00:00Z",
  stage: "VERIFY",
  summary: "Verifying gondola A01.",
  shelf_id: "A01",
};

function append(entry: ActivityEntry) {
  act(() => useRunStore.getState().append(entry));
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  useRunStore.getState().reset();
  useUiStore.setState({
    selectedEntityId: null,
    selectedEntityType: null,
    focusSource: null,
    focusReason: null,
    focusSeq: 0,
    followAgent: true,
    userDragging: false,
    userActiveAt: 0,
  });
  renderHook(() => useAgentFocus());
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useAgentFocus", () => {
  it("focuses the shelf of an agent event and shows the reason", () => {
    render(<AgentFocusCaption />);
    append(verify);

    const ui = useUiStore.getState();
    expect(ui.selectedEntityId).toBe("A01");
    expect(ui.selectedEntityType).toBe(ENTITY_TYPE.Shelf);
    expect(ui.focusSource).toBe(FOCUS_SOURCE.Agent);
    expect(ui.focusSeq).toBe(1);
    expect(screen.getByRole("status").textContent).toContain("Verifying gondola A01.");
  });

  it("focuses again when the agent returns to an entity already selected", () => {
    append({ ...verify, stage: "INVESTIGATE", sku: "P003" });
    append({ ...verify, id: "v2", stage: "ACT", sku: "P003" });
    expect(useUiStore.getState().focusSeq).toBe(2);
  });

  it("leaves the camera alone with Follow agent off", () => {
    useUiStore.getState().setFollowAgent(false);
    append(verify);
    act(() => vi.advanceTimersByTime(AGENT_FOCUS_IDLE_MS * 2));
    expect(useUiStore.getState().selectedEntityId).toBeNull();
    expect(useUiStore.getState().focusSeq).toBe(0);
  });

  it("ignores stages that do not move the camera", () => {
    append({ ...verify, stage: "PLAN" });
    expect(useUiStore.getState().selectedEntityId).toBeNull();
  });

  it("waits while the user drags the camera, then focuses the latest event once they are idle", () => {
    useUiStore.getState().markUserActivity(true);
    append(verify);
    append({ ...verify, id: "v2", stage: "ACT", sku: "P003", summary: "Restocking P003." });
    act(() => vi.advanceTimersByTime(AGENT_FOCUS_IDLE_MS * 3));
    expect(useUiStore.getState().selectedEntityId).toBeNull();

    act(() => useUiStore.getState().markUserActivity(false));
    act(() => vi.advanceTimersByTime(AGENT_FOCUS_IDLE_MS - 1));
    expect(useUiStore.getState().selectedEntityId).toBeNull();
    act(() => vi.advanceTimersByTime(AGENT_FOCUS_IDLE_MS));
    const ui = useUiStore.getState();
    expect(ui.selectedEntityId).toBe("P003");
    expect(ui.focusReason).toBe("Restocking P003.");
    expect(ui.focusSeq).toBe(1);
  });

  it("does not take the camera right after the user selected something", () => {
    useUiStore.getState().select("P001");
    append(verify);
    expect(useUiStore.getState().selectedEntityId).toBe("P001");
    act(() => vi.advanceTimersByTime(AGENT_FOCUS_IDLE_MS));
    expect(useUiStore.getState().selectedEntityId).toBe("A01");
  });

  it("drops the caption once the user selects something else", async () => {
    // The caption's exit animation runs on real frames.
    vi.useRealTimers();
    render(<AgentFocusCaption />);
    append(verify);
    act(() => useUiStore.getState().select("P001"));
    const ui = useUiStore.getState();
    expect(ui.focusSource).toBe(FOCUS_SOURCE.User);
    expect(ui.focusReason).toBeNull();
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });
});
