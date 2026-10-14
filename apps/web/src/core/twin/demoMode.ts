/**
 * True when `?twin=demo` may turn on: in a development build, or in a build made with
 * `VITE_ALLOW_DEMO=true` (the hosted demo). Other `?twin=` dev twins stay development-only.
 */
export function demoAllowed(): boolean {
  return import.meta.env.DEV || import.meta.env.VITE_ALLOW_DEMO === "true";
}

/**
 * True when the page was opened with `?twin=demo` where the demo is allowed (`demoAllowed`):
 * the twin is the stocked demo store and the panels read demo data (fixtures/demo) where
 * apps/api serves none yet. Never on in tests, or in a production build without the flag.
 */
export function isDemoMode(): boolean {
  if (!demoAllowed() || typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("twin") === "demo";
}
