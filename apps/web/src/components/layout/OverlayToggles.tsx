import { useTranslation } from "react-i18next";
import { AlertIcon, SimulationIcon } from "@/components/icons";
import { OVERLAY, OVERLAYS, type Overlay } from "@/enums/ui.enum";
import { useUiStore } from "@/state/ui.store";

const ICONS: Record<Overlay, typeof AlertIcon> = {
  [OVERLAY.StockoutRisk]: AlertIcon,
  [OVERLAY.AiChanges]: SimulationIcon,
};

/**
 * The Overlays group over the 3D view (#213): Stockout risk and AI changes, each turned on
 * or off on its own, unlike the lens and view switches beside it. Narrow screens show the
 * icons only.
 */
export function OverlayToggles() {
  const { t } = useTranslation();
  const overlays = useUiStore((state) => state.overlays);
  const toggleOverlay = useUiStore((state) => state.toggleOverlay);

  return (
    <div role="group" aria-label={t("overlay.label")} className="segmented segmented-glass overlay-toggles">
      {OVERLAYS.map((overlay) => {
        const Icon = ICONS[overlay];
        const on = overlays[overlay];
        return (
          <button
            key={overlay}
            type="button"
            aria-pressed={on}
            aria-label={t(`overlay.${overlay}`)}
            title={t(`overlay.${overlay}Hint`)}
            data-selected={on}
            className="segmented-option overlay-toggle"
            onClick={() => toggleOverlay(overlay)}
          >
            {on ? <span className="segmented-thumb" /> : null}
            <span className="segmented-content">
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="segmented-label">{t(`overlay.${overlay}`)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
