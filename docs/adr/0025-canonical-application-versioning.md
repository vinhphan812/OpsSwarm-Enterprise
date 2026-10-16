# 0025. Canonicalize application versioning across API and Web

Date: 2026-10-16

## Status

Accepted

## Context

The repository had no canonical contract for "what version is running".
Hard-coded strings were scattered across surfaces — `FastAPI(version="0.1.0")`
in `apps/api/retailtwin_api/main.py`, `"0.0.0"` in `apps/web/package.json`, no
`CHANGELOG.md`, no git release tags — and there was no machine-checkable link
between an arbitrary commit SHA on `main` and the artifact the API or the Web
bundle claimed to be.

The consequences were operational:

- An incident dashboard cannot tell which revision of the API answered a
  `/health` call without reading container labels or commit logs.
- The Web UI cannot tell the user which release it is running, so a bug report
  rarely includes the bundle identity.
- Release tagging is ad hoc; there is no record of what changed between two
  arbitrary commits.

The chosen shape must hold for both surfaces (the FastAPI process and the
Vite-built bundle), survive the loss of the `.git` directory in a Docker image
or a Cloud Run revision, and be cheap enough that CI can enforce it on every
PR.

## Decision

The canonical SemVer is the single line in `/VERSION` at the repository
root. The contract is:

- **API**: `apps/api/retailtwin_api/version.py` reads `/VERSION` at module
  load, validates it as strict SemVer (`MAJOR.MINOR.PATCH`), and exposes
  `__version__`, `git_sha`, `build_time`, and `full_version()`. The process
  reports them via `GET /version` and adds `version` + `git_sha` to
  `GET /health`. `FastAPI(...)` advertises the same `__version__`, so
  `/openapi.json` matches. `GIT_SHA` is read from the environment at
  process start (CI exports it), with `git rev-parse --short HEAD` as the
  local fallback and `"unknown"` if neither is available.
- **Web**: `apps/web/vite.config.ts` reads `/VERSION` at config time,
  validates the same regex, and injects `import.meta.env.VITE_APP_VERSION`
  plus `VITE_GIT_SHA` into the bundle. `BuildBadge.tsx` renders both in a
  small pinned badge so the running bundle is always traceable.
- **Tagging**: every release commit carries a `vMAJOR.MINOR.PATCH` tag
  matching `/VERSION`.
- **Changelog**: `CHANGELOG.md` uses the Keep-a-Changelog format; a section
  for the released version exists before the tag is pushed.
- **CI gate**: `.github/workflows/version-consistency.yml` runs on every PR.
  It (1) parses `/VERSION`, (2) imports `retailtwin_api.version` and asserts
  it matches, (3) reads the Web config the same way Vite does and asserts
  `VITE_APP_VERSION` matches, (4) when the PR targets a `v*` tag it asserts
  `CHANGELOG.md` has a matching `## [<version>]` section, and (5) fails
  closed if any of those diverge.

Build metadata (`git_sha`) is reported as SemVer build metadata
(`0.8.0+abc1234`); it never alters compatibility and a release's
MAJOR.MINOR.PATCH stays the contract.

## Consequences

- Every PR that touches a release contract — the file, the changelog, or the
  Web config — is blocked if the three views disagree. Drift becomes
  impossible by default.
- `/version`, `/health`, and `/openapi.json` agree on the same identifier,
  which simplifies SLO dashboards and Cloud Run revision labels.
- The Web bundle carries the canonical SemVer in the JavaScript itself; a
  developer running `npm run build` locally sees the version they are testing,
  not `"0.0.0"`.
- CI learns one more always-run gate. Its execution is one Python import and
  one shell regex check; runtime cost is negligible compared to the
  existing mypy/pytest gates.
- A new surface (a future mobile build, a CLI release) reads the same
  `/VERSION` file and gets the contract for free.

- Pull request: (filled in at merge time)
- Issue: #165
- Supersedes:
- Superseded by: