import { create } from "zustand";
import type { ReadFailure } from "@/core/api/readFailure";
import { AGENT_FEED_STATE, type AgentFeedState } from "@/enums/agent.enum";

type AgentFeedStore = {
  /** Where the Live timeline's feed (`GET /agent/events`) stands; `off` where nothing reads it. */
  state: AgentFeedState;
  /** Why the last read failed; null once a read succeeds. The timeline keeps what it had. */
  failure: ReadFailure | null;
  /** When the feed last answered, in ms since the epoch; 0 before it has. */
  readAt: number;
  /** Events the feed has served on this page so far. */
  served: number;
  /** Bumped by `retry`; the feed reads again at once when it changes. */
  attempt: number;
  start: () => void;
  succeed: (events: number) => void;
  fail: (failure: ReadFailure) => void;
  retry: () => void;
};

/** The Live Agent Activity feed's state, so the timeline can tell no events from a failed read. */
export const useAgentFeedStore = create<AgentFeedStore>()((set) => ({
  state: AGENT_FEED_STATE.Off,
  failure: null,
  readAt: 0,
  served: 0,
  attempt: 0,
  start: () => set((feed) => (feed.state === AGENT_FEED_STATE.Off ? { state: AGENT_FEED_STATE.Loading } : {})),
  succeed: (events) =>
    set((feed) => ({ state: AGENT_FEED_STATE.Ready, failure: null, readAt: Date.now(), served: feed.served + events })),
  fail: (failure) => set({ state: AGENT_FEED_STATE.Failed, failure }),
  retry: () => set((feed) => ({ attempt: feed.attempt + 1, state: AGENT_FEED_STATE.Loading })),
}));
