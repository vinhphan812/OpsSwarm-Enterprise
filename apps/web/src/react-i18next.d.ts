/**
 * TypeScript type augmentation for react-i18next.
 *
 * Extends i18next's `TFunction` so that `t()` calls are validated against
 * the full `en` translation resource tree (all namespaces).
 * Without this, strict-mode TypeScript only knows about the built-in
 * `react-i18next` types and rejects `t("brand.xxx")`, `t("footer.xxx")`,
 * `t("overlay.xxx")` etc. as out-of-scope string literals.
 *
 * ADR-0026: added alongside strict:true tsconfig to restore type-safe i18n
 * without loosening the project-wide strictness standard.
 */
import type { Messages } from './i18n/locales/en';

declare module 'i18next' {
  interface CustomTypeOptions {
    /**
     * Typed keys from the translation resource tree, validated at compile time.
     * Must match the resources passed to i18n.init() in src/i18n/index.ts.
     */
    resources: { en: { translation: Messages } };
    /** Matches `lng: "en"` in i18n.init(). */
    lng: 'en';
    /** Matches `returnNull: false` (no null returned for missing keys). */
    returnNull: false;
  }
}
