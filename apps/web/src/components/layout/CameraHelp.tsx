import { Button, Tooltip } from "@heroui/react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

/** Camera gestures, as [key label, action] i18n keys, in the order users reach for them. */
const GESTURES = [
  ["cameraHelp.orbitKey", "cameraHelp.orbit"],
  ["cameraHelp.panKey", "cameraHelp.pan"],
  ["cameraHelp.zoomKey", "cameraHelp.zoom"],
  ["cameraHelp.selectKey", "cameraHelp.select"],
] as const;

/**
 * A "?" button in the bottom-left corner of the 3D view, in dark glass. Hover or focus shows
 * the camera controls; a tap toggles them on touch screens.
 */
export function CameraHelp() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <Tooltip
      isOpen={open}
      onOpenChange={setOpen}
      placement="top-start"
      offset={10}
      delay={0}
      closeDelay={100}
      classNames={{ content: "border border-line bg-panel/95 p-3 text-ink shadow-lg shadow-black/30 backdrop-blur-md" }}
      content={
        <div className="w-80 text-[13px]">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-accent">
            {t("cameraHelp.title")}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
            {GESTURES.map(([key, action]) => (
              <div key={key} className="contents">
                <dt>
                  <kbd className="whitespace-nowrap rounded border border-line bg-card px-1.5 py-0.5 font-sans text-[11px] font-semibold text-ink-soft">
                    {t(key)}
                  </kbd>
                </dt>
                <dd className="text-ink">{t(action)}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-2 border-t border-line pt-2 text-[12px] text-ink-muted">{t("cameraHelp.touch")}</p>
        </div>
      }
    >
      <Button
        isIconOnly
        radius="full"
        disableRipple
        aria-label={t("cameraHelp.label")}
        onPress={() => setOpen((value) => !value)}
        className="h-9 w-9 min-w-0 cursor-pointer bg-panel/75 text-[15px] font-semibold text-ink-muted shadow-lg shadow-black/20 ring-1 ring-line backdrop-blur-md transition-colors duration-200 data-[hover=true]:bg-panel/90 data-[hover=true]:text-ink data-[focus-visible=true]:ring-2 data-[focus-visible=true]:ring-accent/60"
      >
        ?
      </Button>
    </Tooltip>
  );
}
