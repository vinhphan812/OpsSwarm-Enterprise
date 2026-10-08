import { Button } from "@heroui/react";
import type { KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { LANGUAGES } from "@/constants/i18n.constant";
import { currentLanguage, setLanguage } from "@/i18n";

/**
 * Vietnamese / English switch for the top-left corner of the 3D view: a dark glass
 * pill, like the side panel, with an accent thumb that slides to the active language.
 */
export function LanguageToggle() {
  const { t } = useTranslation();
  const active = currentLanguage();
  const index = LANGUAGES.indexOf(active);

  // Arrow keys move the choice, as in any radio group.
  const onKeyDown = (event: KeyboardEvent) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    setLanguage(LANGUAGES[(index + step + LANGUAGES.length) % LANGUAGES.length]);
  };

  return (
    <div
      role="radiogroup"
      aria-label={t("language.label")}
      onKeyDown={onKeyDown}
      className="rounded-full bg-panel/75 p-1 shadow-lg shadow-black/20 ring-1 ring-line backdrop-blur-md transition-colors duration-200 hover:bg-panel/90"
    >
      <div className="relative grid grid-cols-2">
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-1/2 rounded-full bg-accent shadow-sm transition-transform duration-300 ease-out"
          style={{ transform: `translateX(${index * 100}%)` }}
        />
        {LANGUAGES.map((language) => {
          const selected = language === active;
          return (
            <Button
              key={language}
              role="radio"
              aria-checked={selected}
              aria-label={t(`language.${language}`)}
              title={t(`language.${language}`)}
              tabIndex={selected ? 0 : -1}
              onPress={() => setLanguage(language)}
              variant="light"
              radius="full"
              disableRipple
              disableAnimation
              className={`relative h-7 w-11 min-w-0 px-0 text-[11px] font-semibold tracking-[0.08em] transition-colors duration-200 data-[hover=true]:bg-transparent data-[focus-visible=true]:outline-none data-[focus-visible=true]:ring-2 data-[focus-visible=true]:ring-accent/60 ${
                selected ? "cursor-default text-panel" : "cursor-pointer text-ink-muted data-[hover=true]:text-ink"
              }`}
            >
              {language.toUpperCase()}
            </Button>
          );
        })}
      </div>
    </div>
  );
}
