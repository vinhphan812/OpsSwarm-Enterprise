import { Button, Card, CardBody, Chip, Spinner } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";

/**
 * Loading and error states over the 3D view. Before the first state it covers the
 * empty room; once a state is on screen, problems show as a small banner so the
 * last known store stays visible.
 */
export function TwinStatusOverlay() {
  const { t } = useTranslation();
  const hasState = useTwinStore((state) => state.live !== null);
  const status = useTwinStore((state) => state.status);
  const error = useTwinStore((state) => state.error);
  const stale = useTwinStore((state) => state.stale);
  const retry = useTwinStore((state) => state.retry);

  if (!hasState && status === TWIN_STATUS.Loading) {
    return (
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <Spinner size="lg" label={t("twin.loading")} />
      </div>
    );
  }

  if (!hasState && status === TWIN_STATUS.Error) {
    return (
      <div className="absolute inset-0 flex items-center justify-center bg-canvas/40 p-4 backdrop-blur-sm">
        <Card className="w-full max-w-md">
          <CardBody className="gap-3 p-6 text-center">
            <h2 className="text-lg font-semibold text-danger">{t("twin.loadFailed")}</h2>
            <p className="text-sm text-default-600">{error}</p>
            <Button color="primary" className="cursor-pointer" onPress={retry}>
              {t("twin.retry")}
            </Button>
          </CardBody>
        </Card>
      </div>
    );
  }

  if (stale || (hasState && status === TWIN_STATUS.Loading)) {
    return (
      <div className="absolute left-1/2 top-4 flex -translate-x-1/2 items-center gap-2">
        <Chip color="warning" variant="flat">
          {t(stale ? "twin.stale" : "twin.reconnecting")}
        </Chip>
        {stale ? (
          <Button size="sm" variant="flat" className="cursor-pointer" onPress={retry}>
            {t("twin.reconnect")}
          </Button>
        ) : null}
      </div>
    );
  }

  return null;
}
