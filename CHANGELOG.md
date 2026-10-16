# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The canonical SemVer lives in the `VERSION` file at the repo root (ADR 0025);
the entries below are a human-readable companion to that file.

## [Unreleased]

### Added

- _(none yet — changes go here before the next release tag.)_

## [0.8.0] — 2026-10-16

### Added

- Canonical SemVer source of truth at `/VERSION` (ADR 0025). The API process
  (`retailtwin_api.version`) and the Web build (Vite `define` block) both
  derive their reported version from this file, so the runtime and the bundle
  can never drift.
- `GET /version` returns `{version, git_sha, build_time, service,
  full_version}`. Build metadata (`git_sha`) is recorded as SemVer build
  metadata (`MAJOR.MINOR.PATCH+<sha>`) and never alters compatibility.
- `GET /health` now also reports `version` and `git_sha` so liveness probes
  carry the build identity without a separate request.
- `apps/web` displays the canonical SemVer and the build SHA in a small badge
  pinned to the bottom-right of the 3D viewport. The values are read from
  `VITE_APP_VERSION` / `VITE_GIT_SHA`, injected at build time.
- CI consistency gate (`.github/workflows/version-consistency.yml`) runs on
  every PR: it parses `VERSION`, verifies the API module imports the same
  SemVer, verifies the Web bundle imports the same SemVer, and verifies that
  any release-tag PR (matching `vMAJOR.MINOR.PATCH`) carries a matching
  `CHANGELOG.md` section.
- `apps/api/tests/test_version.py` covers VERSION parsing, the `/version`
  route, the extended `/health` payload, the `GIT_SHA` startup contract, and
  the OpenAPI advertised version.
- ADR 0025 — Canonical application versioning.

### Changed

- `FastAPI(title=…, version=…)` now advertises the canonical SemVer from
  `/VERSION` instead of the previous hard-coded `"0.1.0"`; `/openapi.json`
  therefore matches `/version` and `/health`.

## [0.1.0] — Initial API day-0 release

### Added

- First day-0 release of the RetailTwin API (`apps/api`): `/health`, `/ready`,
  `/store`, `/inventory/{sku}`, `POST /events`, and the early analytics routes.
  The release had no canonical SemVer source and no `/version` endpoint —
  superseded by 0.8.0.

[Unreleased]: https://github.com/vinhphan812/retailtwin-ai/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/vinhphan812/retailtwin-ai/compare/v0.1.0...v0.8.0
[0.1.0]: https://github.com/vinhphan812/retailtwin-ai/releases/tag/v0.1.0