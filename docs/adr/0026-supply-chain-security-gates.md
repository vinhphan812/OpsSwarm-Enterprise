# 0026. Add lightweight supply-chain and security gates for release artifacts

Date: 2026-10-16

## Status

Accepted

## Context

PR #188 (issue #146) introduced `.github/workflows/security.yml` and wired it
into the API and Web pipelines as a `workflow_call`. The gate covers secret
scans (Trivy fs `--scanners secret`), Python dependency vulnerabilities
(`pip-audit`), Web production-only `npm audit`, and a Trivy filesystem
vulnerability scan. The Cloud Run job also re-runs Trivy against the freshly
pushed image with `--ignore-unfixed` and HIGH/CRITICAL blocking.

The competition deliverable needs a tighter shape than that baseline without
turning into a vendor platform:

- **Secrets**: the scan is present, but `.env` examples, fixture API keys,
  and the existing `e2077a9` rule set must continue to be allowed while real
  `.env` files, base64 API keys, and PEM blocks are rejected.
- **Container image**: only the Cloud Run job scans the image. PRs that change
  the Dockerfile should also fail if the image runs as UID 0 or carries a
  credential file. The current scan blocks on every HIGH/CRITICAL regardless
  of whether a fix exists.
- **Third-party Actions**: `google-github-actions/auth@v2`,
  `docker/setup-buildx-action@v3`, `docker/build-push-action@v6`, and
  `google-github-actions/deploy-cloudrun@v2` are referenced by tag. A
  compromised upstream tag can run code with `id-token: write` and Cloud Run
  deploy permissions.
- **SBOM**: there is no machine-readable inventory of what shipped in the
  container, so an incident responder cannot answer "what was in
  `retailtwin-api@sha-abc`?" from the repo alone.
- **Job permissions**: only the deploy jobs have explicit `permissions:`
  blocks. The hygiene, lint, and test jobs inherit the repo default which can
  drift.

Two alternatives were set aside:

- **A full enterprise compliance platform** (Sentinel, Snyk, OSS Insight).
  Out of scope for the competition and adds credentials to manage.
- **Blocking competition work on every MEDIUM CVE**. The issue body scopes
  HIGH/CRITICAL only. MEDIUM and LOW are accepted exceptions and recorded in
  the workflow annotation, not the gate.

## Decision

The release gate is layered on top of the existing `security.yml`. Each layer
has a single owner, a documented exception path, and an artifact that proves it
ran.

**Secrets.** Keep the four-pattern scan in `ci.yml` (`Repository Hygiene`)
plus the Trivy `fs --scanners secret` pass. `tests/**`, `*.test.*`, `*_test.*`,
and `.github/workflows/*.yml` are excluded by pattern. Real `.env` files
remain rejected by both `git ls-files` and the Trivy scan. Allow-listed
fixtures (`api_key="sk-test-full-cycle"`, `api_key="key"`, `api_key="local-key"`)
continue to live under `apps/api/tests/` so the existing exception holds.

**Dependency scanning.** The Python job installs `apps/api` into an isolated
virtualenv (`/tmp/retailtwin-app-venv`) and runs `pip-audit` from a second
virtualenv (`/tmp/retailtwin-audit-venv`). The audit reads the app venv's
`site-packages` directory so it inspects exactly what the API ships.
`npm audit --omit=dev --audit-level=high` keeps the gate scoped to production
dependencies only. Both jobs fail on HIGH/CRITICAL; LOW/MEDIUM is an explicit
exception and surfaces in the GitHub Step Summary, not in the gate.

**Container image.** A new `container-image` job in `security.yml` builds the
Dockerfile in CI, scans it with `aquasec/trivy:0.65.0 image --severity
HIGH,CRITICAL --exit-code 1`, and also runs `docker run --user 0:0
--entrypoint id $IMAGE` plus `docker run --entrypoint sh -c "test ! -e
/app/credentials.json && test ! -e /app/service-account.json" $IMAGE` to fail
closed on root execution or a credential file. No-fix HIGH/CRITICAL findings
pass the gate but are written to the GitHub Step Summary as exceptions. The
existing Cloud Run `deploy-cloudrun` job keeps the `--ignore-unfixed` scan as
a defence-in-depth pass.

**Third-party Actions.** Pin the four third-party actions to a full-version
tag and a comment with the commit SHA. `actions/*` keeps major-version tags
and is tracked by Dependabot via `.github/dependabot.yml` (new file). When
Dependabot opens an update, the SHA comment is refreshed by the same PR.

| Action | Pin |
| --- | --- |
| `google-github-actions/auth` | `v2.1.7` (`6fc4af4b145ae7821d527454aa9bd537d1f2dc5f`) |
| `docker/setup-buildx-action` | `v3.10.0` (`b5ca514318bd6ebac0fb2aedd5d36ec1b5c232a2`) |
| `docker/build-push-action` | `v6.18.0` (`263435318d21b8e681c14492fe198d362a7d2c83`) |
| `google-github-actions/deploy-cloudrun` | `v2.7.6` (`251330ba9a8a34bfbc1622895f42e1d53fd14522`) |
| `anchore/sbom-action` | `v0.24.3` (`fffec3d851af758d56fee099cf3fbf8aa8779843`) |

**Job permissions.** Each workflow declares `permissions:` at the top level
with `contents: read` and only adds `id-token: write` on the job that calls
`google-github-actions/auth`. The two existing deploy jobs already follow
this pattern; this record extends it to `ci.yml`, `conflict-markers.yml`,
`security.yml`, and the new `release-gate.yml`.

**SBOM.** A new `.github/workflows/release-gate.yml` runs on push to `main`
after the API deployment job. It uses `anchore/sbom-action@v0.24.3` against
the freshly pushed image `gcr.io/retailtwin-ai-511002/retailtwin-api:${SHA}`
and uploads the SPDX SBOM plus a small `release-evidence.json` containing the
git SHA, image digest, image tag, and Trivy summary as a workflow artifact
named `release-evidence`. The Web release-evidence artifact is produced by
the existing Web `verify` job summary, so this ADR does not add a second Web
artifact.

**Tests.** Two new tests under `apps/api/tests/` lock in the contract:
`test_workflows.py` parses every workflow YAML and `test_supply_chain.py`
asserts that `Dockerfile` runs as a non-root user, that the secret-scan
patterns still match the documented fixtures, and that no workflow references
a third-party action by a floating major tag without a SHA comment.

## Consequences

- **One gate per concern.** Secret, Python dep, Web dep, container image, and
  SBOM each have a single job. A failure points at one cause instead of a
  wall of output.
- **Exception policy is explicit.** HIGH/CRITICAL with no fix pass with an
  annotation. MEDIUM/LOW never fail the gate. The exception list lives in the
  Step Summary so reviewers can see it without opening Trivy.
- **Pinning is centralised.** The four SHAs and the dependabot manifest are
  the only sources of truth for action versions. Dependabot opens PRs against
  `package-ecosystem: github-actions`.
- **No long-lived signing keys in GitHub.** The SBOM is uploaded as a
  workflow artifact; it is not signed in-repo. The `id-token: write`
  permission is only requested by the two existing WIF deploy jobs.
- **One new required check.** `release-gate` joins the four checks named in
  `.github/CI_CONTRACT.md`. It only runs on push to `main`, so PRs do not
  need to be green for the SBOM job to be skipped.
- **Follow-up work.** Issue #146 itself notes that an enterprise platform is
  not in scope; if the team adopts one later, this ADR is the baseline it
  extends.

- Pull request:
- Issue: #146
- Supersedes:
- Superseded by: