# Release Policy

## Purpose and scope

This policy defines how OpsSwarm Enterprise release candidates are built, evidenced, and moved from an immutable Git tag
to a draft GitHub Release. The implemented workflow is `.github/workflows/release.yml`.

The workflow never publishes a release automatically. It may only create or update a draft. Publication remains an
explicit human action after the evidence in this document has been reviewed.

This policy implements the accepted decisions in [ADR-008](../adr/ADR-008_DEPENDENCY_LOCK_RELEASE_POLICY.md), consumes
the quality interface planned in [CI Quality Gates](../triage/historical/CI_QUALITY_GATES_TRIAGE.md), and applies the
artifact and
severity policy in [ADR-010](../adr/ADR-010_SECURITY_WORKFLOW_AND_POLICY.md). Where the linked CI and security documents
describe proposed controls, this policy does not claim those controls have run until the corresponding GitHub checks
exist and report success for the release commit.

## Release eligibility

A release candidate is eligible for drafting only when all of the following are true:

1. An existing tag matches `v*` and identifies the exact commit being built.
2. The tag has a supported semantic version form, and its version without the leading `v` exactly equals
   `project.version` in `pyproject.toml`.
3. The functional `CI` workflow and `Security CI` workflow both report success for the release commit. On a tag push,
   GitHub branch protection or an equivalent repository ruleset must have admitted that tagged commit only after those
   required checks succeeded; the release workflow cannot safely poll concurrently triggered tag workflows. On manual
   dispatch, the workflow additionally queries GitHub Actions and fails closed unless both workflow names already report
   success for the tagged commit. Release consumes these results instead of duplicating their test and scanning logic.
4. The committed `requirements.lock` is the portable, hash-locked pip-tools output derived from the direct runtime input
   `requirements.txt`. CI verifies that input against `pyproject.toml`, regenerates the lock with pip-tools 7.5.2, and
   rejects any diff. Security and release workflows install it with `--require-hashes` in an isolated virtual
   environment;
   vulnerability scans and CycloneDX SBOM generation target that exact environment rather than an editable project
   install.
5. The wheel and source distribution build successfully on Python 3.11. Functional compatibility across Python 3.11,
   3.12, and 3.13 remains owned by the CI matrix.
6. The clean-wheel smoke harness passes from a temporary directory outside the repository with explicit external
   configuration and data paths.
7. SHA-256 checksums, CycloneDX JSON SBOM, and GitHub build-provenance attestations are generated successfully.
8. The shared `scripts/validate-artifacts.py` control from the issue #7 security implementation exists and accepts the
   public evidence before upload. The release workflow intentionally fails closed while that prerequisite is absent.
9. No CRITICAL or HIGH security condition is unresolved. Exceptions require the exact advisory, package and version, an
   expiry of at most 90 days, security-lead approval, and a linked tracker issue. Global pip-audit ignores are
   prohibited.

The release workflow has only two entry points:

- a push of an existing `v*` tag; or
- `workflow_dispatch` with an existing `v*` tag supplied as input.

Manual dispatch does not permit a branch build to masquerade as a release. The workflow resolves and checks out
`refs/tags/<tag>`, then verifies the checked-out commit and package version before any release artifact is built.

## Branch protection prerequisite

**This is a hard prerequisite for tag-push releases.**

The release workflow's "Require prerequisite CI and security checks" step (`.github/workflows/release.yml`) only runs on
`workflow_dispatch`. On a tag push it is unconditionally skipped. Consequently, a tag push **must not proceed** unless
GitHub branch protection or a repository ruleset has already admitted the tagged commit only after `CI` and
`Security CI` both succeeded for that commit.

Before attempting a tag-push release, verify that **one of the following** is configured for the repository's default
branch:

### Option A — Branch protection (legacy)

- **UI path:** Settings > Branches > Protect this branch
- **Branch:** the repository's default branch (currently `master`)
- **Required status checks:** `CI`, `Security CI`
- **Additional:** Require branches to be up to date before merge
- **Bypass:** Only allow bypass by admins

### Option B — Repository ruleset (preferred, replaces branch protection)

- **UI path:** Settings > Rules > Rulesets > New ruleset
- **Name:** e.g. `Release CI Gate`
- **Target branches:** the repository's default branch (currently `master`); use `~DEFAULT` or explicit `master` pattern
- **Rules:**
    - "Require status checks to pass before merging" enabled
    - Required checks: `CI`, `Security CI`
- **Bypass actors:** none (enforce for all, including admins); or restrict to service accounts only

### Verification step

The release workflow includes a pre-flight step that detects the absence of both branch protection and any ruleset
targeting the default branch and **fails immediately** with a setup guide. This step only runs on tag push; it has no
effect on `workflow_dispatch`.

If the default branch name changes in the future, the release workflow will detect it dynamically via
`gh api repos/<owner>/<repo> --jq '.default_branch'` and report the correct name in any error message.

Release tags are immutable. Never move, delete and recreate, or force-update a published tag to correct a release.

If a draft is wrong, keep the audit history, correct the source on the default branch, increment `project.version`, and
create a new tag. A draft may be deleted or superseded, but its tag must not be reused for different source. If a
published release is defective, document the defect, mark the release accordingly if repository policy permits, ship a
new version, and direct consumers to the replacement. Rollback means reinstalling a known-good earlier version; it never
means retargeting the defective version's tag.

## Clean-install proof

The installable unit is the wheel. The workflow builds one wheel and one source distribution, creates a temporary
working directory outside the checkout, copies the repository's safe test configuration to that external location, and
invokes:

```text
python scripts/smoke-wheel.py <absolute-wheel-path> <absolute-external-config-path>
```

The harness creates a fresh virtual environment, installs the wheel, verifies that `opsswarm` resolves from that
environment's `site-packages`, runs `pip check`, starts the API outside the repository, and verifies the `/health`
response. `OPSWARM_CONFIG` and `OPSWARM_DATA_DIR` are explicit external paths during the smoke run. Temporary processes
and files are cleaned up even when a check fails.

## Wheel contents and external deployment assets

Per ADR-008-3, the wheel is a pure Python package and contains only:

- `opsswarm/` package code;
- distribution metadata under `*.dist-info/`; and
- the license file.

The following are deliberately excluded from the wheel and must be supplied by the deployment environment:

- `config/` files, by external mount or environment-specific generation;
- `openclaw/` patches and workspaces;
- `skills/` definitions;
- `scripts/` deployment or operator utilities; and
- `tests/`.

No production configuration, OpenClaw workspace, runtime data, credential, token, or secret may be staged as release
evidence or attached to a GitHub Release. The safe test configuration used by the smoke check remains temporary and is
not uploaded.

Wheel proof and deployment proof are distinct. Passing the clean-wheel smoke test demonstrates that the Python
distribution installs and starts with explicitly supplied external configuration; it does not demonstrate that external
OpenClaw assets have been deployed or validated in a target environment.

## Evidence inventory

Every successful draft run produces the following evidence:

| Evidence                    | Purpose                                                                                                                                       | Publication/retention                            |
|-----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------|
| `*.whl`                     | Installable Python distribution                                                                                                               | Draft GitHub Release and workflow artifact       |
| `*.tar.gz`                  | Source distribution                                                                                                                           | Draft GitHub Release and workflow artifact       |
| `SHA256SUMS.txt`            | Portable SHA-256 digest list for both distributions                                                                                           | Draft GitHub Release and workflow artifact       |
| `sbom.cdx.json`             | Reproducible CycloneDX JSON inventory of the isolated environment installed from hash-locked `requirements.lock` using `cyclonedx-bom==7.4.0` | Draft GitHub Release and workflow artifact       |
| GitHub artifact attestation | OIDC-backed build provenance binding the release files to the workflow run                                                                    | GitHub attestation store; linked from draft body |
| `PROVENANCE.md`             | Attestation URL, workflow-run URL, and verification command                                                                                   | Workflow artifact only                           |

The combined `release-evidence-<tag>` workflow artifact is retained for 30 days under ADR-010. The draft release
contains exactly the wheel, source distribution, checksum file, and SBOM. Its body references the GitHub attestation and
the retained workflow evidence.

## Permissions and action pinning

The release job declares only the permissions needed for its staged operations:

- `contents: write` permits checkout/read access and creation or update of a draft GitHub Release;
- `actions: read` permits the fail-closed prerequisite check to read workflow results for the tagged commit;
- `id-token: write` permits OIDC identity issuance for provenance; and
- `attestations: write` permits publishing the artifact attestation.

No package, deployment, environment-secret, pull-request, issue, or administration permission is granted. The `release`
environment can be configured with required reviewers to add an organization-level approval gate before the job starts.

Every third-party GitHub Action is pinned to a full immutable commit SHA. The corresponding human-readable release tag
is retained as an inline YAML comment so upgrades remain reviewable.

## Draft-to-publish approval

Creation of a draft is not approval to publish. Before selecting **Publish release**, a release owner must manually
verify:

1. the tag, package version, and target commit agree;
2. the required CI and security checks for that commit succeeded;
3. all four release attachments are present and `SHA256SUMS.txt` verifies them;
4. the SBOM parses as CycloneDX JSON and reflects the locked dependencies;
5. the attestation exists and verifies for each attached file;
6. artifact-redaction validation passed and no external config, OpenClaw data, credentials, or runtime data is attached;
7. CRITICAL/HIGH findings are absent or covered by a valid documented waiver; and
8. release notes and compatibility statements are accurate.

A human with release authority then publishes the existing draft in GitHub. The workflow does not contain an automatic
publication path.

## Provenance lookup and verification

The draft body and `PROVENANCE.md` record the attestation URL and workflow-run URL. After downloading an attachment,
verify it against the repository identity:

```text
gh attestation verify <artifact> --repo <owner>/<repository>
```

Also verify the distributions against `SHA256SUMS.txt` using a local SHA-256 tool. The checksum file is generated with
Python rather than platform-specific shell utilities, so its format is stable across runner environments.

## Post-publish reinstall verification

After publication, a release owner must perform a consumer-side verification from a clean, non-repository directory:

1. Download the published wheel, `SHA256SUMS.txt`, and `sbom.cdx.json` from the GitHub Release.
2. Verify the wheel checksum and GitHub attestation.
3. Create a fresh virtual environment using each supported Python version, 3.11 through 3.13.
4. Install the downloaded wheel without using the repository checkout.
5. Supply an explicit safe external `OPSWARM_CONFIG` and isolated `OPSWARM_DATA_DIR`.
6. Run `pip check`, import `opsswarm.api`, confirm its origin is `site-packages`, and verify the `/health` contract.
7. Separately verify the required external configuration, OpenClaw workspace, and skills in the target deployment
   procedure.

Record the command outputs and release URL in the release record. If verification fails, do not move the tag; follow the
immutable-tag rollback process and issue a new version.
