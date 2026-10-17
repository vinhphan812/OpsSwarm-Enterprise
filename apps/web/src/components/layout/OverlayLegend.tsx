import { useTranslation } from "react-i18next";
import { isDemoMode } from "@/core/twin/demoMode";
import { OVERLAY, RISK_BANDS } from "@/enums/ui.enum";
import { useStockoutRisk } from "@/hooks/stockoutRisk.hook";
import { useUiStore } from "@/state/ui.store";

/**
 * The stockout-risk legend, bottom left over the 3D view while that overlay is on: the four
 * bands and the forecast horizon, or, on Live, that no risk is served yet (TODO(BE)).
 */
export function OverlayLegend() {
  const { t } = useTranslation();
  const on = useUiStore((state) => state.overlays[OVERLAY.StockoutRisk]);
  const risks = useStockoutRisk();
  if (!on) return null;
  const hours = risks?.[0]?.horizon_hours;

  return (
    <section className="overlay-legend" aria-label={t("overlay.legend.title")}>
      <h2 className="overlay-legend-title">
        {t("overlay.legend.title")}
        {hours ? <span className="overlay-legend-horizon">{t("overlay.legend.horizon", { hours })}</span> : null}
      </h2>
      {risks ? (
        <>
          <ul className="overlay-legend-bands">
            {RISK_BANDS.map((band) => (
              <li key={band} data-band={band}>
                <span className={`overlay-legend-swatch overlay-legend-swatch-${band}`} aria-hidden />
                {t(`overlay.legend.${band}`)}
              </li>
            ))}
          </ul>
          <p className="overlay-legend-note">
            {t("overlay.legend.noData")}
            {isDemoMode() ? ` ${t("overlay.legend.demo")}` : null}
          </p>
        </>
      ) : (
        <p className="overlay-legend-note">{t("overlay.legend.notServed")}</p>
      )}
    </section>
  );
}
