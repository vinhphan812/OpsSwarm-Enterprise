import { Button, Chip, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";

/**
 * Loading and error states over the 3D view. The store stays visible underneath: with
 * empty shelves until the first state, then the last known state. Problems show as a
 * small banner; the toast carries the details.
 */
export function TwinStatusOverlay() {
  const { t } = useTranslation();
  const hasState = useTwinStore((state) => state.live !== null);
  const status = useTwinStore((state) => state.status);
  const stale = useTwinStore((state) => state.stale);
  const retry = useTwinStore((state) => state.retry);

  if (!hasState && status === TWIN_STATUS.Loading) {
    return (
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <Spinner size="lg" label={t("twin.loading")} />
      </div>
    );
  }

  const failed = !hasState && status === TWIN_STATUS.Error;
  if (failed || stale || (hasState && status === TWIN_STATUS.Loading)) {
    return (
      <div className="absolute left-1/2 top-20 z-10 flex -translate-x-1/2 items-center gap-2">
        <Chip color={failed ? "danger" : "warning"} variant="flat">
          {t(failed ? "twin.loadFailed" : stale ? "twin.stale" : "twin.reconnecting")}
        </Chip>
        {failed || stale ? (
          <Button size="sm" variant="flat" className="cursor-pointer" onPress={retry}>
            {t(failed ? "twin.retry" : "twin.reconnect")}
          </Button>
        ) : null}
      </div>
    );
  }

  return null;
}
