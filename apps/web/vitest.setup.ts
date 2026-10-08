import i18n from "./src/i18n";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Tests read English text, whatever the machine's locale.
await i18n.changeLanguage("en");
