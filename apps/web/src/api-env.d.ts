interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** "true" lets a production build open `?twin=demo` (the hosted demo). */
  readonly VITE_ALLOW_DEMO?: string;
  /** Canonical SemVer sourced from the /VERSION file at the repo root. ADR 0025. */
  readonly VITE_APP_VERSION?: string;
  /** Short commit SHA the bundle was built from; falls back to "unknown". */
  readonly VITE_GIT_SHA?: string;
}