// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentActivityPanel } from "@/components/layout/AgentActivityPanel";
import { ApiError } from "@/core/api/client";
import { AGENT_FEED_STATE } from "@/enums/agent.enum";
import { useAgentFeed } from "@/hooks/agentFeed.hook";
import { useAgentFeedStore } from "@/state/agentFeed.store";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import type { AgentEvent, AgentEventsResponse, RetailTwinClient } from "@/types/api.type";

vi.mock("@/components/status/StoreStatus", () => ({ StoreStatus: () => null }));

MotionGlobalConfig.skipAnimations = true;

const POLL = 1000;

function event(id: string, stage = "INVESTIGATE"): AgentEvent {
  return { id, ts: "2026-10-18T10:00:00Z", stage, status: "ok", correlation_id: "run-1", summary: `${stage} ${id}`, sku: "P003" };
}

/** A client whose `GET /agent/events` answers with `answer`, one call at a time. */
function feedClient(answer: (since: string | null | undefined) => Promise<AgentEventsResponse>) {
  return { agentEvents: vi.fn(answer) } as unknown as RetailTwinClient;
}

const unavailable = () => new ApiError(503, "simulation_store_unavailable", "Simulation store unavailable.", "web-123");

beforeEach(() => {
  vi.useFakeTimers();
  useRunStore.getState().reset();
  useAgentFeedStore.setState(useAgentFeedStore.getInitialState(), true);
  usePanelStore.setState({ open: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useAgentFeed", () => {
  it("reads every page of the feed into the timeline, then resumes from the last cursor", async () => {
    const pages: Record<string, AgentEventsResponse> = {
      start: { events: [event("a"), event("b")], cursor: "2" },
      "2": { events: [event("c")], cursor: null },
    };
    const client = feedClient(async (since) => pages[since ?? "start"]);
    renderHook(() => useAgentFeed(true, client, POLL));
    await act(() => vi.advanceTimersByTimeAsync(0));

    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a", "b", "c"]);
    expect(useAgentFeedStore.getState()).toMatchObject({ state: AGENT_FEED_STATE.Ready, served: 3, failure: null });

    await act(() => vi.advanceTimersByTimeAsync(POLL));
    expect(vi.mocked(client.agentEvents).mock.calls.map(([since]) => since)).toEqual([null, "2", "2"]);
    // The page read again adds nothing twice.
    expect(useRunStore.getState().activity).toHaveLength(3);
  });

  it("says the feed failed, keeps the timeline it had, and recovers on the next poll", async () => {
    let fail = false;
    const client = feedClient(async () => {
      if (fail) throw unavailable();
      return { events: [event("a")], cursor: null };
    });
    renderHook(() => useAgentFeed(true, client, POLL));
    await act(() => vi.advanceTimersByTimeAsync(0));

    fail = true;
    await act(() => vi.advanceTimersByTimeAsync(POLL));
    expect(useAgentFeedStore.getState()).toMatchObject({
      state: AGENT_FEED_STATE.Failed,
      failure: { route: "GET /agent/events", status: 503, code: "simulation_store_unavailable", correlationId: "web-123" },
    });
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a"]);

    fail = false;
    await act(() => vi.advanceTimersByTimeAsync(POLL));
    expect(useAgentFeedStore.getState()).toMatchObject({ state: AGENT_FEED_STATE.Ready, failure: null });
  });

  it("reads nothing when off, on the demo and the dev twins", async () => {
    const client = feedClient(async () => ({ events: [], cursor: null }));
    renderHook(() => useAgentFeed(false, client, POLL));
    await act(() => vi.advanceTimersByTimeAsync(POLL * 3));
    expect(client.agentEvents).not.toHaveBeenCalled();
    expect(useAgentFeedStore.getState().state).toBe(AGENT_FEED_STATE.Off);
  });
});

describe("the Agent Activity timeline on Live", () => {
  /** The panel, fed by `client` the way TwinPage feeds it. */
  function Live({ client }: { client: RetailTwinClient }) {
    useAgentFeed(true, client, POLL);
    return <AgentActivityPanel />;
  }

  it("says the feed answered with no events, not that it failed", async () => {
    render(<Live client={feedClient(async () => ({ events: [], cursor: null }))} />);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("No agent activity yet. GET /agent/events answered with no events.")).toBeTruthy();
    expect(screen.queryByRole("alert", { name: "Agent feed failed" })).toBeNull();
  });

  it("shows a failed feed with its status, code and correlation id, and Retry reads it again", async () => {
    let fail = true;
    const client = feedClient(async () => {
      if (fail) throw unavailable();
      return { events: [event("a")], cursor: null };
    });
    render(<Live client={client} />);
    await act(() => vi.advanceTimersByTimeAsync(0));

    const card = screen.getByRole("alert", { name: "Agent feed failed" });
    expect(card.textContent).toContain("HTTP 503 · simulation_store_unavailable");
    expect(card.textContent).toContain("GET /agent/events");
    expect(card.textContent).toContain("web-123");
    expect(screen.queryByText(/No agent activity yet/)).toBeNull();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.queryByRole("alert", { name: "Agent feed failed" })).toBeNull();
    expect(screen.getByText("INVESTIGATE a")).toBeTruthy();
  });

  it("keeps the events it had when a later read fails, and says they are no longer updating", async () => {
    let fail = false;
    const client = feedClient(async () => {
      if (fail) throw unavailable();
      return { events: [event("a")], cursor: null };
    });
    render(<Live client={client} />);
    await act(() => vi.advanceTimersByTimeAsync(0));
    fail = true;
    await act(() => vi.advanceTimersByTimeAsync(POLL));

    expect(screen.getByRole("alert", { name: "Agent feed failed. The timeline shows the last events it read." })).toBeTruthy();
    expect(screen.getByText("INVESTIGATE a")).toBeTruthy();
  });
});
