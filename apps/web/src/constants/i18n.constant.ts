/** Supported languages; the first is the default. */
export const LANGUAGES = ["vi", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

export const DEFAULT_LANGUAGE: Language = "vi";

/** localStorage key that remembers the user's language. */
export const LANGUAGE_STORAGE_KEY = "retailtwin.language";

/** Locale passed to the UI kit for dates, numbers, and built-in labels. */
export const UI_LOCALE: Record<Language, string> = { vi: "vi-VN", en: "en-US" };

/** Currency each language shows money in. Amounts are not converted between currencies. */
export const CURRENCY: Record<Language, string> = { vi: "VND", en: "USD" };
