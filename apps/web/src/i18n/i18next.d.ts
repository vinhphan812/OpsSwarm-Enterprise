import "i18next";
import type { Messages } from "./locales/en";

/** Typed keys: `t("twin.loading")` checks against the English messages. */
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: Messages };
  }
}
