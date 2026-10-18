import { useTranslation } from "react-i18next";
import { DEMO_PATH, LIVE_PATH, demoAllowed, isDemoMode } from "@/core/twin/demoMode";
import { isApiTwin } from "@/core/twin/devSources";
import { VIEW_MODE } from "@/enums/ui.enum";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

/**
 * The top bar: what RetailTwin is, where its data comes from (the synthetic demo store, or
 * the Live Twin of apps/api), the store the twin reports, and whether the 3D view shows
 * Live or a Simulation. Where the demo is allowed, a link opens the other twin (a full page
 * load, since the twin source is picked once per page).
 */
export function TwinHeader() {
  const { t } = useTranslation();
  const storeId = useTwinStore((state) => state.live?.store_id ?? null);
  const simulation = useUiStore((state) => state.viewMode === VIEW_MODE.Simulation);
  const demo = isDemoMode();

  return (
    <header className="twin-header">
      <div className="twin-header-brand">
        <span className="twin-header-name">{t("brand.name")}</span>
        <span className="twin-header-tagline">{t("brand.tagline")}</span>
      </div>
      <div className="twin-header-status">
        {demo ? (
          <span className="twin-header-source" data-source="demo" title={t("brand.demoHint")}>
            {t("brand.demo")}
          </span>
        ) : isApiTwin() ? (
          <span className="twin-header-source" data-source="live" title={t("brand.liveDataHint")}>
            {t("brand.liveData")}
          </span>
        ) : null}
        <span className="twin-header-store" title={t("brand.storeHint")}>
          {storeId ?? "—"}
        </span>
        <span className="twin-header-mode" data-mode={simulation ? VIEW_MODE.Simulation : VIEW_MODE.Live}>
          {simulation ? t("brand.simulation") : t("brand.live")}
        </span>
        {demoAllowed() ? (
          <a className="twin-header-switch" href={demo ? LIVE_PATH : DEMO_PATH}>
            {demo ? t("brand.openLive") : t("brand.openDemo")}
          </a>
        ) : null}
      </div>
    </header>
  );
}
