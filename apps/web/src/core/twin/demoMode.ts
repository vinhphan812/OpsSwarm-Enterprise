/**
 * True when the page was opened with `?twin=demo` in a development build: the twin is
 * the stocked demo store and the panels read demo data (fixtures/demo) where apps/api
 * serves none yet. Never on in production or in tests.
 */
export function isDemoMode(): boolean {
  if (!import.meta.env.DEV || typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("twin") === "demo";
}
