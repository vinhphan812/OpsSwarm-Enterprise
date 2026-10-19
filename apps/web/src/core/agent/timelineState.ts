import { AGENT_FEED_STATE, TIMELINE_STATE, type AgentFeedState, type TimelineState } from "@/enums/agent.enum";

/**
 * Why the timeline shows what it shows, so an empty one never passes for a quiet agent when
 * it is not: the demo's replay (no apps/api), the connection gone, the feed failing, its first
 * read still out, or the feed answering with no event. Null when nothing reads the feed.
 */
export function timelineState({
  live,
  feed,
  online,
  stale,
}: {
  /** The page reads apps/api (`isApiTwin`). */
  live: boolean;
  feed: AgentFeedState;
  /** `navigator.onLine`. */
  online: boolean;
  /** The Live Twin's feed dropped (`useTwinStore().stale`). */
  stale: boolean;
}): TimelineState | null {
  if (!live) return TIMELINE_STATE.ReplayIdle;
  if (!online || stale) return TIMELINE_STATE.Disconnected;
  if (feed === AGENT_FEED_STATE.Failed) return TIMELINE_STATE.ApiFailed;
  if (feed === AGENT_FEED_STATE.Loading) return TIMELINE_STATE.Loading;
  // Nothing reads the feed: nothing to say about it.
  if (feed === AGENT_FEED_STATE.Off) return null;
  return TIMELINE_STATE.NoEvents;
}
