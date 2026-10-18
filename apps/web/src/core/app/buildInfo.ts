/**
 * The build the page runs: the app version as `VITE_APP_VERSION`, and the short Git SHA the
 * build was made from (`vite.config.ts`). TODO(#165): `VITE_APP_VERSION` from the canonical
 * /VERSION, so apps/api and apps/web report one string; until then a build shows its SHA only.
 */
export function buildLabel(env: Pick<ImportMetaEnv, "VITE_APP_VERSION" | "VITE_GIT_SHA"> = import.meta.env): string | null {
  const version = env.VITE_APP_VERSION?.trim();
  const sha = env.VITE_GIT_SHA?.trim();
  if (version && sha) return `v${version.replace(/^v/, "")}+${sha}`;
  if (version) return `v${version.replace(/^v/, "")}`;
  return sha || null;
}
