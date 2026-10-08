import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { formatters, type Formatters } from "@/core/utils/format";
import { currentLanguage } from "@/i18n";

/** Formatters for the active language; components re-render with new ones when it changes. */
export function useFormat(): Formatters {
  useTranslation();
  const language = currentLanguage();
  return useMemo(() => formatters(language), [language]);
}
