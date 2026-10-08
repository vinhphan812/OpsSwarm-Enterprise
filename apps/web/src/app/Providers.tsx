import { HeroUIProvider, ToastProvider } from "@heroui/react";
import { MotionConfig } from "framer-motion";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { BrowserRouter, useHref, useNavigate } from "react-router";
import { UI_LOCALE } from "@/constants/i18n.constant";
import { currentLanguage } from "@/i18n";

/**
 * HeroUI links and buttons with `href` navigate through the router, not a page load,
 * and its built-in labels and formats follow the app language.
 */
function UiProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  // Re-renders on a language change.
  useTranslation();
  return (
    <HeroUIProvider navigate={navigate} useHref={useHref} locale={UI_LOCALE[currentLanguage()]}>
      <ToastProvider placement="top-right" maxVisibleToasts={3} />
      {/* Animations follow the OS "reduce motion" setting. */}
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </HeroUIProvider>
  );
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    <BrowserRouter>
      <UiProvider>{children}</UiProvider>
    </BrowserRouter>
  );
}
