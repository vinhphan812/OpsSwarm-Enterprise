import { useEffect } from "react";
import type { TwinSource } from "@/core/api/sources/TwinSource";
import { InvalidTwinStateError } from "@/core/api/validate";
import i18n from "@/i18n";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";
import { errorMessage, notify } from "@/core/notify";
import { connectTwin } from "@/core/twin/twinConnection";

/**
 * Keeps the twin store connected to `source` until unmount, and reconnects on
 * `retry`. Load failures and feed drops are shown as toasts.
 */
export function useTwinSource(source: TwinSource) {
  const attempt = useTwinStore((state) => state.attempt);

  useEffect(() => {
    const { setLive, setStatus, setStale } = useTwinStore.getState();
    return connectTwin(source, {
      onState: setLive,
      onStatus: (status, error) => {
        setStatus(status, error === undefined ? null : errorMessage(error));
        if (status === TWIN_STATUS.Error) notify.error(i18n.t("twin.loadFailed"), error);
      },
      onFeedError: (error) => {
        setStale(true);
        const title = i18n.t(error instanceof InvalidTwinStateError ? "twin.unreadableUpdate" : "twin.feedLost");
        notify.warning(title, i18n.t("twin.showingStale", { error: errorMessage(error) }));
      },
      onFeedRestored: () => setStale(false),
    });
  }, [source, attempt]);
}
