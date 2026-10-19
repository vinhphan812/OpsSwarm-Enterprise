import { useTranslation } from "react-i18next";
import { ActivityIcon, OfflineIcon } from "@/components/icons";
import { ReadFailureCard } from "@/components/common/ReadStatus";
import { timelineState } from "@/core/agent/timelineState";
import { isApiTwin } from "@/core/twin/devSources";
import { TIMELINE_STATE, type TimelineState } from "@/enums/agent.enum";
import { useOnline } from "@/hooks/online.hook";
import { useAgentFeedStore } from "@/state/agentFeed.store";
import { useTwinStore } from "@/state/twin.store";

/** Where the timeline's feed stands, from the page, the connection and `GET /agent/events`. */
export function useTimelineState(): TimelineState | null {
  const feed = useAgentFeedStore((state) => state.state);
  const online = useOnline();
  const stale = useTwinStore((state) => state.stale);
  return timelineState({ live: isApiTwin(), feed, online, stale });
}

/** The feed's failure as a card: HTTP status, code, route, time, correlation id, and Retry. */
function FeedFailure({ title }: { title: string }) {
  const failure = useAgentFeedStore((state) => state.failure);
  const retry = useAgentFeedStore((state) => state.retry);
  if (!failure) return null;
  return <ReadFailureCard title={title} failure={failure} onRetry={retry} />;
}

/**
 * The empty timeline, saying why it is empty: the feed has no event, failed (with its
 * failure), is not reachable, is still loading, or (the demo) no replay is playing. With no
 * feed state (nothing reads it), it only says there is no activity.
 */
export function TimelineEmpty({ state, filtered }: { state: TimelineState | null; filtered: boolean }) {
  const { t } = useTranslation();
  if (filtered) {
    return (
      <div className="empty">
        <ActivityIcon className="empty-icon" />
        <p>{t("alerts.noRunYet")}</p>
      </div>
    );
  }
  if (state === TIMELINE_STATE.ApiFailed) return <FeedFailure title={t("activity.feed.failed")} />;
  return (
    <div className="empty" data-state={state ?? undefined}>
      {state === TIMELINE_STATE.Disconnected ? <OfflineIcon className="empty-icon" /> : <ActivityIcon className="empty-icon" />}
      <p>{state ? t(`activity.feed.${state}`) : t("activity.empty")}</p>
    </div>
  );
}

/** Above a timeline that has entries: says when they are no longer updating, and why. Nothing while the feed is healthy. */
export function TimelineAlert({ state }: { state: TimelineState | null }) {
  const { t } = useTranslation();
  if (state === TIMELINE_STATE.ApiFailed) return <FeedFailure title={t("activity.feed.failedKeeping")} />;
  if (state === TIMELINE_STATE.Disconnected) {
    return (
      <p className="activity-feed-alert" role="status">
        <OfflineIcon className="h-3.5 w-3.5 shrink-0" />
        {t("activity.feed.disconnectedKeeping")}
      </p>
    );
  }
  return null;
}
