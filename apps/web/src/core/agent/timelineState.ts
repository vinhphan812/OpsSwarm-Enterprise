/** Timeline state management. */
import { type AgentFeedState } from "@/enums/agent.enum";

export type TimelineStatus = "connected" | "disconnected" | "loading" | "error";

export interface TimelineStateData {
  status: TimelineStatus;
  feedState: AgentFeedState;
  lastEvent?: string;
}

export interface TimelineStateOptions {
  live: boolean;
  feed: AgentFeedState;
  online: boolean;
  stale: boolean;
}

/** Get current timeline state. */
export function timelineState({ live, feed, online, stale }: TimelineStateOptions): TimelineStateData {
  let status: TimelineStatus = "disconnected";
  
  if (live && online && !stale) {
    if (feed === "success") {
      status = "connected";
    } else if (feed === "loading") {
      status = "loading";
    } else if (feed === "failed") {
      status = "error";
    }
  }
  
  return { status, feedState: feed };
}
