import { useTranslation } from "react-i18next";
import { LIVE_PATH, isDemoMode } from "@/core/twin/demoMode";

/**
 * A full-width line under the header on the demo (`/demo`, `?twin=demo`, and `/` of the hosted
 * demo): the store on screen is synthetic, not live store telemetry, and nothing here writes to
 * the Live Twin. It links to `/live`. Renders nothing off the demo.
 */
export function TwinDemoBanner() {
  const { t } = useTranslation();
  if (!isDemoMode()) return null;
  return (
    <div className="twin-demo-banner" role="note" aria-label={t("brand.demoBannerLabel")}>
      <span className="twin-demo-banner-tag">{t("brand.demoBannerTag")}</span>
      <span className="twin-demo-banner-text">{t("brand.demoBanner")}</span>
      <a className="twin-header-switch" href={LIVE_PATH}>
        {t("brand.openLive")}
      </a>
    </div>
  );
}
