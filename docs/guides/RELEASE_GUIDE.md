# Release Guide

## Overview

This guide covers the step-by-step process for producing a draft GitHub Release of OpsSwarm Enterprise.
The authoritative policy is [RELEASE_POLICY.md](./RELEASE_POLICY.md); this guide is the operator-facing
companion that explains how to run the workflow and verify the output.

Releases are driven entirely by the [release.yml](../../.github/workflows/release.yml) workflow.
No manual artifact manipulation is required or permitted.

---

## Prerequisites

Before attempting a release, confirm the following are in place:

| Check | How to verify |
|---|---|
| Default branch protection or ruleset with required `CI` and `Security CI` status checks | Settings > Branches or Settings > Rules in the GitHub repository |
| All CI and Security CI checks pass on the intended release commit | GitHub Actions UI for that commit |
| `pyproject.toml` `project.version` matches the intended `v*` tag (without the `v`) | `python -c "import tomllib; print(tomllib.load(open('pyproject.toml'),'rb')['project']['version'])"` |
| `requirements.lock` is committed and contains no uncommitted dependency changes | `git status requirements.lock` |
| `scripts/smoke-wheel.py` and `scripts/validate-artifacts.py` exist | `ls scripts/smoke-wheel.py scripts/validate-artifacts.py` |
| `config/test.yaml` exists | `ls config/test.yaml` |

If branch protection is absent, the workflow will fail at the pre-flight step on a tag push.
Set it up before proceeding (see RELEASE_POLICY.md for options).

---

## Release entry points

The workflow has two entry points:

### A — Tag push (standard path)

1. Merge the release commit to the default branch and confirm CI + Security CI pass.
2. Tag the release commit:
   ```text
   git tag v2.2.0
   git push origin v2.2.0
   ```
3. The `release.yml` workflow triggers automatically.
4. Monitor the run at: https://github.com/<owner>/<repo>/actions/workflows/release.yml

This path requires branch protection to have admitted the tagged commit — the workflow does not
re-run CI. Use this for releases that have already gone through the full PR gate.

### B — Workflow dispatch (backfill path)

Use this to draft a release from an existing tag without pushing a new tag:

1. Go to https://github.com/<owner>/<repo>/actions/workflows/release.yml
2. Click **Run workflow** and enter the existing tag (e.g. `v2.2.0`).
3. The workflow validates that `CI` and `Security CI` succeeded for that tag's commit before proceeding.

---

## Release workflow stages

The workflow runs two jobs in sequence:

### `release` job

1. Resolves and validates the tag against the semantic version policy.
2. Checks out the exact immutable tag ref (not a branch).
3. Verifies the checked-out commit and `pyproject.toml` version agree with the tag.
4. Installs the hash-locked runtime in an isolated venv.
5. Runs the fail-closed branch-protection pre-flight (tag-push only).
6. Polls for prerequisite CI and Security CI success (dispatch only).
7. Validates `requires-python >=3.11` matches the CI owned Python 3.11–3.13 matrix.
8. Builds wheel and source distribution.
9. Generates SHA-256 checksums and reproducible CycloneDX JSON SBOM from the locked venv.
10. Validates artifact completeness (wheel, sdist, checksums, SBOM).
11. Runs `scripts/validate-artifacts.py` to confirm no secrets or internal paths are in the evidence.
12. Attests all four evidence files via GitHub OIDC build provenance.
13. Creates a **draft** GitHub Release (never published automatically).

### `smoke` job (runs twice: wheel and sdist)

1. Downloads the distributions and safe test config from the release job artifact.
2. Creates a fresh venv using the managed Python 3.11 runner.
3. Runs `scripts/smoke-wheel.py` which:
   - Installs the artifact (wheel or sdist) in the fresh venv.
   - Verifies `opsswarm` imports from `site-packages` (not repo source).
   - Runs `pip check` for broken dependencies.
   - Starts the API with an external config and `OPSWARM_DATA_DIR` from outside the checkout.
   - Verifies the `/health` response matches the expected contract.

Both the wheel and sdist smoke runs must succeed for the release evidence to be complete.

---

## After the draft is created

Do **not** click **Publish release** until the following have been verified:

1. **Tag, version, and commit agree.** The draft body and workflow run URL confirm the target SHA.
2. **Required checks confirmed.** CI and Security CI checks are green on the release commit.
3. **All four release attachments present.** Wheel, source distribution, `SHA256SUMS.txt`, `sbom.cdx.json`.
4. **Checksums verified** (download `SHA256SUMS.txt` and verify with `sha256sum -c SHA256SUMS.txt`).
5. **SBOM parses.** `python -m json.tool sbom.cdx.json` succeeds and shows the locked dependency graph.
6. **Attestations exist.** The draft body contains the GitHub attestation URL. Verify each file:
   ```text
   gh attestation verify <file> --repo <owner>/<repository>
   ```
7. **Artifact validation passed.** `scripts/validate-artifacts.py` ran without error in the workflow.
8. **CRITICAL/HIGH security findings absent.** Check the Security CI run or `gh code-scanning query` for the release commit.
9. **Release notes accurate.** Edit the draft body to include version highlights and breaking changes if applicable.

Only after all checks pass should a release owner publish the draft in GitHub.

---

## Post-publish consumer verification

After publication, perform a clean-install verification from a non-repository directory:

```text
# Download the wheel and SHA256SUMS.txt from the GitHub Release
# Verify checksums
sha256sum -c SHA256SUMS.txt

# Verify GitHub attestation
gh attestation verify opsswarm_openclaw_github-*.whl --repo <owner>/<repository>

# Clean-install on each supported Python version (3.11–3.13)
python3.11 -m venv verify-venv
verify-venv/bin/python -m pip install opsswarm_openclaw_github-*.whl
verify-venv/bin/python -m pip check

# Verify import origin and health contract
OPSWARM_CONFIG=<safe-test-config.yaml> \
OPSWARM_DATA_DIR=/tmp/verify-data \
  verify-venv/bin/python -c "import opsswarm.api; print(opsswarm.api.__file__)"
```

The module path must be under `site-packages`, not a local checkout. Run `/health` and confirm
`{"ok": true, "version": "<version>", "architecture": "openclaw+github"}`.

Record the verification command outputs and the release URL in the release record.

---

## Rollback and defect handling

If a published release is defective:

1. **Do not move or delete the tag.** Tags are immutable.
2. Document the defect in the GitHub Release notes.
3. Fix the root cause on the default branch.
4. Increment `project.version` in `pyproject.toml`.
5. Tag and release the corrected version.
6. Notify consumers to pin to the new version.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow fails at "Fail fast if branch protection absent" | Tag push without branch protection or ruleset | Configure protection per RELEASE_POLICY.md, then re-tag |
| Workflow times out at prerequisite check | CI or Security CI still running on the release commit | Wait for CI to complete, then retry dispatch |
| Smoke test fails "Module not from site-packages" | Checkout directory on `sys.path` (should not happen with external cwd) | Inspect the smoke-wheel.py `check_import_origin` logic |
| `pip check` fails in smoke | Dependency metadata mismatch in wheel vs requirements.lock | Rebuild and verify `requirements.lock` is current |
| Artifact validation fails | `validate-artifacts.py` detected an unexpected path | Inspect the workflow run artifact and `validate-artifacts.py` output |
