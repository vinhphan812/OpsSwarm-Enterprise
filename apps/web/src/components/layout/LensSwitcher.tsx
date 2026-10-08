import { useTranslation } from "react-i18next";
import { Segmented } from "@/components/commerce/Segmented";
import { LENSES, type Lens } from "@/enums/ui.enum";
import { usePanelStore } from "@/state/panel.store";
import { useUiStore } from "@/state/ui.store";
import { LENS_VIEW } from "./lens";

/**
 * Operations / Revenue / Promotions switch at the top of the 3D view, in the language switch's dark glass.
 * Picking a lens opens the side panel on it. Narrow screens show the icons only.
 */
export function LensSwitcher() {
  const { t } = useTranslation();
  const lens = useUiStore((state) => state.lens);
  const setLens = useUiStore((state) => state.setLens);
  const setOpen = usePanelStore((state) => state.setOpen);

  const pick = (next: Lens) => {
    setLens(next);
    setOpen(true);
  };

  return (
    <Segmented
      variant="glass"
      label={t("lens.label")}
      layoutId="lens"
      value={lens}
      onChange={pick}
      options={LENSES.map((value) => {
        const { Icon } = LENS_VIEW[value];
        return { value, label: t(`lens.${value}`), icon: <Icon className="h-3.5 w-3.5 shrink-0" /> };
      })}
    />
  );
}
