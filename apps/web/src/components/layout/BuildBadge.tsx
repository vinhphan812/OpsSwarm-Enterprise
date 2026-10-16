import { useMemo } from "react";

/** Canonical SemVer the bundle was built from. Sourced from /VERSION at build time (ADR 0025). */
const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "0.0.0";
/** Short commit SHA the bundle was built from. CI exports GIT_SHA; local dev falls back to `git rev-parse`. */
const GIT_SHA = import.meta.env.VITE_GIT_SHA ?? "unknown";

/**
 * Small build-identity badge pinned to the bottom-right of the 3D viewport.
 * Renders the canonical SemVer plus the build SHA so the visible bundle is
 * always traceable to a release (ADR 0025).
 *
 * Pure CSS — no icons, no images — so the dev tools and the demo screenshots
 * stay readable regardless of theme or contrast.
 */
export function BuildBadge() {
  const label = useMemo(() => `v${APP_VERSION}`, []);
  const tooltip = useMemo(
    () => `Build ${APP_VERSION}+${GIT_SHA}\nSourced from /VERSION at the repo root.`,
    [],
  );

  return (
    <div
      className="build-badge"
      role="status"
      aria-label={`Application version ${APP_VERSION}, build ${GIT_SHA}`}
      title={tooltip}
      data-app-version={APP_VERSION}
      data-git-sha={GIT_SHA}
    >
      <span className="build-badge-version">{label}</span>
      <span className="build-badge-sha" aria-hidden>
        {GIT_SHA}
      </span>
    </div>
  );
}