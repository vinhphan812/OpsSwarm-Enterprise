import { heroui } from "@heroui/react";

/**
 * HeroUI theme as a Tailwind plugin, loaded from App.css. The dark theme mirrors the
 * @theme palette there, so HeroUI cards, chips and buttons match the side panel.
 */
export default heroui({
  defaultTheme: "dark",
  themes: {
    dark: {
      colors: {
        background: "#121820",
        foreground: "#e8edf2",
        content1: "#18202b",
        content2: "#1e2733",
        content3: "#2a3544",
        content4: "#3d4d61",
        divider: "#2a3544",
        focus: "#d5e4f5",
        primary: { DEFAULT: "#d5e4f5", foreground: "#121820" },
        danger: { DEFAULT: "#ffb4a8", foreground: "#121820" },
      },
    },
  },
});
