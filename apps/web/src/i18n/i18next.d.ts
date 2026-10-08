import "i18next";
import type { Messages } from "./locales/vi";

/** Typed keys: `t("twin.loading")` checks against the Vietnamese messages. */
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: Messages };
  }
}
