import { Button, Spinner } from "@heroui/react";
import { AnimatePresence, motion } from "framer-motion";
import type { ComponentType } from "react";
import { useTranslation } from "react-i18next";
import { AlertIcon, OfflineIcon, RetryIcon } from "@/components/icons";
import { TWIN_STATUS } from "@/enums/twin.enum";
import type { Messages } from "@/i18n/locales/en";
import { useTwinStore } from "@/state/twin.store";

type TwinKey = `twin.${keyof Messages["twin"]}`;

/** What the notice says for each problem. `action` is the retry button's label, if it has one. */
type Notice = {
  key: string;
  tone: "danger" | "warning" | "info";
  /** No state on screen yet, so the notice takes the middle of the view. */
  blocking: boolean;
  title: TwinKey;
  hint: TwinKey;
  action?: TwinKey;
  Icon?: ComponentType<{ className?: string }>;
};

const TONE = {
  danger: { badge: "bg-alert/12 text-alert ring-alert/30", dot: "bg-alert" },
  warning: { badge: "bg-warning/12 text-warning ring-warning/30", dot: "bg-warning" },
  info: { badge: "bg-accent/10 text-accent ring-accent/25", dot: "bg-accent" },
} as const;

const FADE = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.2 } };

/** Picks the notice for the twin's status, or none while the live state is current. */
function useNotice(): Notice | null {
  const hasState = useTwinStore((state) => state.live !== null);
  const status = useTwinStore((state) => state.status);
  const stale = useTwinStore((state) => state.stale);

  if (status === TWIN_STATUS.Loading) {
    // No state yet: the first load. With a state: a reconnect after a drop or a retry.
    return hasState
      ? { key: "reconnecting", tone: "info", blocking: false, title: "twin.reconnecting", hint: "twin.reconnectingHint" }
      : { key: "loading", tone: "info", blocking: true, title: "twin.loading", hint: "twin.reconnectingHint" };
  }
  if (!hasState && status === TWIN_STATUS.Error) {
    return {
      key: "failed",
      tone: "danger",
      blocking: true,
      title: "twin.loadFailed",
      hint: "twin.loadFailedHint",
      action: "twin.retry",
      Icon: AlertIcon,
    };
  }
  if (stale) {
    return {
      key: "stale",
      tone: "warning",
      blocking: false,
      title: "twin.stale",
      hint: "twin.staleHint",
      action: "twin.reconnect",
      Icon: OfflineIcon,
    };
  }
  return null;
}

/** No state to show yet: a centered card over the dimmed, empty store. */
function BlockingNotice({ notice, onRetry }: { notice: Notice; onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <motion.div
      {...FADE}
      role={notice.action ? "alert" : "status"}
      className="absolute inset-0 z-10 flex items-center justify-center bg-canvas/25 p-4 backdrop-blur-[2px]"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 6 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.22, ease: "easeOut" }}
        className="flex w-full max-w-sm flex-col items-center rounded-2xl bg-panel/90 px-8 py-7 text-center text-ink shadow-2xl shadow-black/30 ring-1 ring-line backdrop-blur-md"
      >
        <span
          className={`mb-4 flex h-14 w-14 items-center justify-center rounded-full ring-1 ${TONE[notice.tone].badge}`}
        >
          {notice.Icon ? <notice.Icon className="h-6 w-6" /> : <Spinner size="md" color="current" />}
        </span>
        <h2 className="text-base font-semibold">{t(notice.title)}</h2>
        <p className="mt-1.5 text-sm leading-5 text-ink-muted">{t(notice.hint)}</p>
        {notice.action ? (
          <Button
            radius="md"
            disableRipple
            onPress={onRetry}
            startContent={<RetryIcon className="h-4 w-4" />}
            className="mt-5 cursor-pointer bg-accent px-5 font-medium text-canvas data-[hover=true]:bg-accent-hover"
          >
            {t(notice.action)}
          </Button>
        ) : null}
      </motion.div>
    </motion.div>
  );
}

/** The last state is still on screen: a slim status pill hanging from the top edge. */
function InlineNotice({ notice, onRetry }: { notice: Notice; onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <motion.div
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      role={notice.action ? "alert" : "status"}
      title={t(notice.hint)}
      className="absolute left-1/2 top-0 z-10 flex -translate-x-1/2 items-center gap-2.5 rounded-b-xl bg-panel/85 py-1.5 pl-3.5 pr-1.5 text-xs text-ink-soft shadow-md shadow-black/20 ring-1 ring-line backdrop-blur-md"
    >
      <span className="relative flex h-2 w-2" aria-hidden>
        <span className={`absolute inset-0 animate-ping rounded-full opacity-60 ${TONE[notice.tone].dot}`} />
        <span className={`relative h-2 w-2 rounded-full ${TONE[notice.tone].dot}`} />
      </span>
      <span className="whitespace-nowrap">{t(notice.title)}</span>
      {notice.action ? (
        <button
          type="button"
          onClick={onRetry}
          className="flex cursor-pointer items-center gap-1 rounded-lg px-2 py-1 font-medium text-accent transition-colors hover:bg-card"
        >
          <RetryIcon className="h-3 w-3" />
          {t(notice.action)}
        </button>
      ) : (
        <span className="pr-2" />
      )}
    </motion.div>
  );
}

/**
 * Loading and error states over the 3D view. The store stays visible underneath: with
 * empty shelves until the first state, then the last known state. Without a state the
 * notice is a centered card; with one it is a slim pill at the top. The toast carries
 * the details.
 */
export function TwinStatusOverlay() {
  const retry = useTwinStore((state) => state.retry);
  const notice = useNotice();

  return (
    <AnimatePresence>
      {notice?.blocking ? <BlockingNotice key={notice.key} notice={notice} onRetry={retry} /> : null}
      {notice && !notice.blocking ? <InlineNotice key={notice.key} notice={notice} onRetry={retry} /> : null}
    </AnimatePresence>
  );
}
