/**
 * True when the demo may turn on: in a development build, or in a build made with
 * `VITE_ALLOW_DEMO=true` (the hosted demo). Other `?twin=` dev twins stay development-only.
 */
export function demoAllowed(): boolean {
  return import.meta.env.DEV || import.meta.env.VITE_ALLOW_DEMO === "true";
}

/** The page that always opens the demo store, where the demo is allowed. */
export const DEMO_PATH = "/demo";
/** The page that always reads the Live Twin from apps/api, even in the hosted demo. */
export const LIVE_PATH = "/live";

/**
 * Whether the URL asks for the demo: `?twin=demo`, or `/demo`. On `/` with no `?twin=`, a
 * hosted demo build (`VITE_ALLOW_DEMO=true`) opens the demo too, so its bare URL lands on it;
 * `/live` is always Live regardless of `?twin=` (pathname is authoritative over query params).
 */
export function demoRequested({ pathname, search }: Pick<Location, "pathname" | "search">): boolean {
  // LIVE_PATH is authoritative — never activate demo on /live regardless of ?twin=
  if (pathname === LIVE_PATH) return false;
  const twin = new URLSearchParams(search).get("twin");
  if (twin !== null) return twin === "demo";
  if (pathname === DEMO_PATH) return true;
  return pathname === "/" && import.meta.env.VITE_ALLOW_DEMO === "true";
}

/**
 * True when the page asks for the demo (`demoRequested`) where the demo is allowed
 * (`demoAllowed`): the twin is the stocked demo store and the panels read demo data
 * (fixtures/demo) where apps/api serves none yet. Never on in tests, or in a production build
 * without the flag.
 */
export function isDemoMode(): boolean {
  if (!demoAllowed() || typeof window === "undefined") return false;
  return demoRequested(window.location);
}
