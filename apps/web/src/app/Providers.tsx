import { HeroUIProvider, ToastProvider } from "@heroui/react";
import { MotionConfig } from "framer-motion";
import type { ReactNode } from "react";
import { BrowserRouter, useHref, useNavigate } from "react-router";
import { LOCALE } from "@/constants/i18n.constant";
import { isDemoMode } from "@/core/twin/demoMode";

/** How far toasts sit from the top: below the header, and below the demo banner on the demo. */
const TOAST_OFFSET_PX = 40;
const DEMO_TOAST_OFFSET_PX = 66;

/**
 * HeroUI links and buttons with `href` navigate through the router, not a page load,
 * and its built-in labels and formats use the app locale. Toasts never cover the header's
 * data chip or the demo banner.
 */
function UiProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  return (
    <HeroUIProvider navigate={navigate} useHref={useHref} locale={LOCALE}>
      <ToastProvider
        placement="top-right"
        maxVisibleToasts={3}
        toastOffset={isDemoMode() ? DEMO_TOAST_OFFSET_PX : TOAST_OFFSET_PX}
      />
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
