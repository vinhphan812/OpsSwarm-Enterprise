import { useEffect } from "react";
import i18n from "@/i18n";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";
import { notify } from "@/core/notify";

/**
 * Tells the user when the browser goes offline or back online. Back online, it
 * reconnects to the twin if the last load failed or the feed dropped.
 */
export function useNetworkStatus() {
  useEffect(() => {
    const onOffline = () => notify.warning(i18n.t("network.offline"), i18n.t("network.offlineBody"));
    const onOnline = () => {
      notify.success(i18n.t("network.online"));
      const { status, stale, retry } = useTwinStore.getState();
      if (status === TWIN_STATUS.Error || stale) retry();
    };
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, []);
}
