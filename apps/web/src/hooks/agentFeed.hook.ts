import { useEffect } from "react";
import { AGENT_FEED_POLL_MS, AGENT_FEED_PAGES } from "@/constants/app.constant";
import { defaultClient } from "@/core/api/client";
import { readFailureOf } from "@/core/api/readFailure";
import { toActivityEntry } from "@/core/demo/demoRunner";
import { useAgentFeedStore } from "@/state/agentFeed.store";
import { useRunStore } from "@/state/run.store";
import type { RetailTwinClient } from "@/types/api.type";

const ROUTE = "GET /agent/events";

/**
 * The Live timeline: reads `GET /agent/events` now and every `pollMs`, page by page, into the
 * run store, which keeps each event once. It resumes from the last cursor the feed served, so
 * a poll reads only what is new. A failed read keeps the timeline as it was and says why
 * (`useAgentFeedStore`); the next poll, or Retry, reads again. Off (`enabled` false) on the demo
 * and the `?twin=` dev twins, which read no apps/api: the timeline then never says the feed failed.
 */
export function useAgentFeed(enabled: boolean, client: RetailTwinClient = defaultClient, pollMs = AGENT_FEED_POLL_MS) {
  const attempt = useAgentFeedStore((state) => state.attempt);

  useEffect(() => {
    if (!enabled) return;
    const feed = useAgentFeedStore.getState();
    feed.start();
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let resume: string | null = null;

    const read = async () => {
      let cursor = resume;
      let events = 0;
      try {
        for (let page = 0; page < AGENT_FEED_PAGES; page += 1) {
          const answer = await client.agentEvents(cursor);
          if (cancelled) return;
          answer.events.map(toActivityEntry).forEach(useRunStore.getState().append);
          events += answer.events.length;
          if (answer.cursor === null || answer.cursor === cursor) break;
          cursor = resume = answer.cursor;
        }
        useAgentFeedStore.getState().succeed(events);
      } catch (error) {
        if (!cancelled) useAgentFeedStore.getState().fail(readFailureOf(error, ROUTE));
      }
      if (!cancelled) timer = setTimeout(read, pollMs);
    };

    void read();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [enabled, client, pollMs, attempt]);
}
