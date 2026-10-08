import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { en } from "./locales/en";

/** English only. Text still goes through `t()`, so a language can be added later. */
void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: "en",
  // React escapes output already.
  interpolation: { escapeValue: false },
});

export default i18n;
