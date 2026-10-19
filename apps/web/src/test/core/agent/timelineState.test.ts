import { describe, expect, it } from "vitest";
import { timelineState } from "@/core/agent/timelineState";
import { AGENT_FEED_STATE, TIMELINE_STATE } from "@/enums/agent.enum";

const live = { live: true, feed: AGENT_FEED_STATE.Ready, online: true, stale: false } as const;

describe("timelineState", () => {
  it("tells a feed with no events from a failed one", () => {
    expect(timelineState(live)).toBe(TIMELINE_STATE.NoEvents);
    expect(timelineState({ ...live, feed: AGENT_FEED_STATE.Failed })).toBe(TIMELINE_STATE.ApiFailed);
  });

  it("says disconnected when the browser is offline or the Live feed dropped, whatever the last read did", () => {
    expect(timelineState({ ...live, online: false })).toBe(TIMELINE_STATE.Disconnected);
    expect(timelineState({ ...live, stale: true, feed: AGENT_FEED_STATE.Failed })).toBe(TIMELINE_STATE.Disconnected);
  });

  it("is the idle replay on the demo, which never reads the Live agent", () => {
    expect(timelineState({ ...live, live: false, feed: AGENT_FEED_STATE.Off })).toBe(TIMELINE_STATE.ReplayIdle);
    expect(timelineState({ ...live, live: false, online: false })).toBe(TIMELINE_STATE.ReplayIdle);
  });

  it("waits for the feed's first answer, and says nothing when nothing reads the feed", () => {
    expect(timelineState({ ...live, feed: AGENT_FEED_STATE.Loading })).toBe(TIMELINE_STATE.Loading);
    expect(timelineState({ ...live, feed: AGENT_FEED_STATE.Off })).toBeNull();
  });
});
