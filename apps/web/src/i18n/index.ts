import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { en } from "./locales/en";
import { vi } from "./locales/vi";
import { DEFAULT_LANGUAGE, LANGUAGES, LANGUAGE_STORAGE_KEY, type Language } from "@/constants/i18n.constant";

const isLanguage = (value: unknown): value is Language => LANGUAGES.includes(value as Language);

/** The language the user picked last, if storage is available. */
function savedLanguage(): Language | null {
  try {
    const value = globalThis.localStorage?.getItem(LANGUAGE_STORAGE_KEY);
    return isLanguage(value) ? value : null;
  } catch {
    return null;
  }
}

/** The first supported language in the browser's preferences. */
function browserLanguage(): Language | null {
  const preferred = typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language];
  return preferred.map((tag) => tag.slice(0, 2).toLowerCase()).find(isLanguage) ?? null;
}

void i18n.use(initReactI18next).init({
  resources: { vi: { translation: vi }, en: { translation: en } },
  lng: savedLanguage() ?? browserLanguage() ?? DEFAULT_LANGUAGE,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: LANGUAGES,
  // React escapes output already.
  interpolation: { escapeValue: false },
});

function syncDocumentLanguage(language: string) {
  if (typeof document !== "undefined") document.documentElement.lang = language;
}
syncDocumentLanguage(i18n.language);
i18n.on("languageChanged", syncDocumentLanguage);

/** The active language, narrowed to a supported one. */
export function currentLanguage(): Language {
  return isLanguage(i18n.resolvedLanguage) ? i18n.resolvedLanguage : DEFAULT_LANGUAGE;
}

/** Switches the language and remembers the choice for the next visit. */
export function setLanguage(language: Language) {
  void i18n.changeLanguage(language);
  try {
    globalThis.localStorage?.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Storage is blocked; the choice lasts for this visit only.
  }
}

export default i18n;
