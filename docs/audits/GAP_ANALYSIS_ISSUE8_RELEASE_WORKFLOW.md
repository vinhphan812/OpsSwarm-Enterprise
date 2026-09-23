# GAP ANALYSIS: Issue #8 Release Workflow

**Task:** t_445c6a63
**Auditor:** dev-ops
**Date:** 2026-09-22
**Status:** ANALYSIS COMPLETE

---

## Executive Summary

The release workflow (`.github/workflows/release.yml`) is structurally sound in its core logic, but it **cannot run to
completion today** because two hard prerequisite files are absent. Additionally, the SBOM tool invocation uses a
deprecated interface. Four cross-cutting gaps were identified. Eight narrowly scoped implementation/QA cards were
created.

---

## Evidence Inventory: What Was Audited

| File                                                 | Status      | Notes                                                         |
| ---------------------------------------------------- | ----------- | ------------------------------------------------------------- |
| `.github/workflows/release.yml`                      | EXISTS      | 326 lines, well-structured                                    |
| `requirements.txt`                                   | EXISTS      | 9 lines, correct format                                       |
| `requirements.txt`                                   | EXISTS      | 537 lines, pip-tools hash lock                                |
| `scripts/smoke-wheel.py`                             | EXISTS      | 235 lines, full smoke harness                                 |
| `docs/guides/RELEASE_POLICY.md`                      | EXISTS      | 133 lines, policy document                                    |
| `docs/adr/ADR-008_DEPENDENCY_LOCK_RELEASE_POLICY.md` | EXISTS      | 201 lines, ADR document                                       |
| `docs/adr/ADR-010_SECURITY_WORKFLOW_AND_POLICY.md`   | EXISTS      | 653 lines, security ADR                                       |
| `scripts/validate-artifacts.py`                      | **MISSING** | Hard gate in release.yml line 256                             |
| `artifacts/` directory                               | **MISSING** | Required for upload; gitignore lacks entry                    |
| `.github/workflows/security.yml`                     | **MISSING** | Required prerequisite (workflow names "CI" and "Security CI") |

---

## Finding 1: `scripts/validate-artifacts.py` — MISSING (BLOCKING)

**Severity:** CRITICAL
**Location:** `release.yml:256-262` and `release.yml:294-297`
**ADR Contract:** ADR-010-3 ("Redaction Validation")
**Policy Reference:** `RELEASE_POLICY.md:22`

The release workflow has a **fail-closed hard gate** requiring this script to exist:

```yaml
# release.yml:256-259
test -f scripts/validate-artifacts.py || {
  echo "scripts/validate-artifacts.py is required from the issue #7 security implementation." >&2
  exit 1
}
```

This step runs twice: once after staging evidence (line 252) and once after provenance record (line 290). The script
must validate `SHA256SUMS.txt`, `sbom.cdx.json`, and `PROVENANCE.md`.

ADR-010-3 specifies the required validation contract:

- No generic long tokens (`[A-Za-z0-9+/]{40,}`)
- No GitHub tokens (`gh[pousr]_[A-Za-z0-9]{36,}`)
- No OpenAI keys (`sk-[A-Za-z0-9]{48,}`)
- No Slack tokens (`xox[pborsa]-[A-Za-z0-9]{10,}`)
- Exit 0 if clean, exit 1 if secrets detected

**Current evidence:** `find` confirms the file does not exist.

**Impact:** The release workflow will fail at the first validation step on every run until this file exists. No release
can be drafted.

---

## Finding 2: `artifacts/` Directory and `.gitignore` Entry — MISSING (BLOCKING)

**Severity:** CRITICAL
**Location:** `release.yml:184-185` (mkdir), `release.yml:299-306` (upload)
**ADR Contract:** ADR-010-3
**Policy Reference:** `RELEASE_POLICY.md:79`

The workflow creates `artifacts/release/` and copies distributions there. However:

1. **`artifacts/` does not exist** — `find` confirmed absence.
2. **`.gitignore` lacks an `artifacts/` entry** — current entries are `dist*` and `build` only.

Without the gitignore entry, a developer who runs the workflow locally (or has local-only artifact generation) risks
committing security CI outputs (SBOMs, pip-audit results, license scans). The release workflow also
`cp dist/*.whl dist/*.tar.gz artifacts/release/` — if `artifacts/` is added to git, those wheel/sdist files could
accidentally be committed.

**ADR-010-3 contract:**

```
artifacts/           # Created by CI, gitignored
  bandit.json
  pip-audit.json
  licenses.json
  sbom.cdx.json
  release/           # release workflow subdir
```

---

## Finding 3: `.github/workflows/security.yml` — MISSING (BLOCKING on workflow_dispatch)

**Severity:** HIGH
**Location:** `release.yml:99-164` (prerequisite check)
**ADR Contract:** ADR-010-1
**Policy Reference:** `RELEASE_POLICY.md:17`

The "Require prerequisite CI and security checks" step (line 99) is gated on `github.event_name == 'workflow_dispatch'`.
It queries GitHub Actions API and requires two workflow names: **"CI"** and **"Security CI"**:

```python
# release.yml:118
required = {"CI", "Security CI"}
```

The workflow checks that both have run and succeeded for the tagged commit before proceeding.

**Evidence:** `ls .github/workflows/` shows only `release.yml`. The "CI" workflow was not in the audit scope but is
referenced; the "Security CI" workflow (`security.yml`) is confirmed absent.

**Impact on push-triggered releases:** The prerequisite check is skipped on tag push (only runs on `workflow_dispatch`).
On push, the workflow relies on branch protection/rulesets to have enforced the checks before the tag was allowed. This
is documented in `RELEASE_POLICY.md:17` but is a silent assumption if branch protection is not configured.

**Impact on workflow_dispatch:** Will fail because "Security CI" workflow does not exist.

---

## Finding 4: Stale Audit Finding — `cyclonedx-py` Is the Correct CLI

**Corrected by:** t_af933042
**Original finding (FAKE):** `cyclonedx-py` was flagged as incorrect; `cyclonedx-pip` was claimed to be the correct CLI.
**Actual fact:** `cyclonedx-pip` does **not exist** in `cyclonedx-bom==7.4.0`. The sole console entrypoint is
`cyclonedx-py`. Verified:

```bash
$ pip install cyclonedx-bom==7.4.0
$ cyclonedx-pip --help   # bash: cyclonedx-pip: command not found
$ cyclonedx-py --help   # shows full usage output
```

The `release.yml:271` invocation is correct:

```bash
cyclonedx-py requirements requirements.txt \
  --pyproject pyproject.toml \
  --mc-type application \
  --output-format JSON \
  --output-reproducible \
  --output-file artifacts/release/sbom.cdx.json
```

The ADR-010-1 open item "Update SBOM step to `cyclonedx-pip`" was itself incorrect and is superseded by this correction.

---

## Finding 5: `pip-tools` Not in `requirements.txt` — Tool Absent from Lock File

**Severity:** MEDIUM
**Location:** `release.yml:96`
**ADR Contract:** ADR-008-1
**Policy Reference:** `requirements.txt:2`

The release workflow installs pip-tools for lock regeneration:

```bash
python -m pip install --require-hashes -r requirements.txt
python -m pip install build==1.3.0 cyclonedx-bom==7.4.0
```

`pip-tools` (specifically `pip-compile`) is NOT in `requirements.txt` — it is a build-time tool only, which is correct
behavior (pip-compile is a build/CI tool, not a runtime dependency). This is not a gap.

**However:** The workflow hard-codes `build==1.3.0` and `cyclonedx-bom==7.4.0` without hashes. This is acceptable for
build-time tools but creates a minor reproducibility concern if these tools change behavior. ADR-010-2 pins these in
`pyproject.toml` dev dependencies; the release workflow duplicates the pin without following the same source of truth.

---

## Finding 6: Stale Audit Finding — `--output-reproducible` Flag Is Supported

**Corrected by:** t_af933042
**Original finding (FAKE):** `--output-reproducible` was claimed to be unsupported by the `cyclonedx-bom` CLI.
**Actual fact:** `cyclonedx-py requirements --help` confirms `--output-reproducible` is a valid flag:

```
--output-reproducible
  Whether to go the extra mile and make the output reproducible.
  This might result in loss of time- and random-based values. If the
  environment variable SOURCE_DATE_EPOCH holds a valid UNIX timestamp,
  then it is used as the SBOM's timestamp, instead of omitting it.
```

The `release.yml:271-276` invocation is correct as-is.

---

## Finding 7: Tag Push vs. workflow_dispatch Asymmetry — Silent Branch Protection Assumption

**Severity:** LOW
**Location:** `release.yml:99-100`, `RELEASE_POLICY.md:17`
**Policy Reference:** `RELEASE_POLICY.md:17`

The prerequisite CI/security check step (lines 99-164) only runs on `workflow_dispatch`. On tag push, it is silently
skipped:

```yaml
if: github.event_name == 'workflow_dispatch'
```

`RELEASE_POLICY.md:17` documents this: "On a tag push, GitHub branch protection or an equivalent repository ruleset must
have admitted that tagged commit only after those required checks succeeded."

This is a documented assumption, but it cannot be verified from local files. If branch protection is not configured (
e.g., the repo is new or rulesets are absent), a tag push would proceed to build artifacts without requiring the
CI/security checks.

**Evidence:** No branch protection ruleset configuration is visible in the repo. This is an operational assumption that
must be verified by someone with repository admin access.

---

## Finding 8: `PROVENANCE.md` Not Listed in Draft Release Files

**Severity:** LOW (informational)
**Location:** `release.yml:323-326`
**Policy Reference:** `RELEASE_POLICY.md:79`

The evidence inventory in `RELEASE_POLICY.md:79` shows `PROVENANCE.md` as "Workflow artifact only" (not published to
draft release). However, the draft release `files:` block (line 322) correctly omits `PROVENANCE.md`:

```yaml
files: |
     artifacts/release/*.whl
     artifacts/release/*.tar.gz
     artifacts/release/SHA256SUMS.txt
     artifacts/release/sbom.cdx.json
```

This is correct — `PROVENANCE.md` is retained only in the workflow artifact (30-day retention). No gap here.

---

## Summary Table

| #   | Finding                                              | Severity         | Type             | Local / CI-Required / Runtime | Blocking?                 |
| --- | ---------------------------------------------------- | ---------------- | ---------------- | ----------------------------- | ------------------------- |
| 1   | `scripts/validate-artifacts.py` absent               | CRITICAL         | Missing file     | Local                         | YES                       |
| 2   | `artifacts/` dir missing + no gitignore entry        | CRITICAL         | Missing file     | Local                         | YES                       |
| 3   | `security.yml` absent (blocks workflow_dispatch)     | HIGH             | Missing workflow | GitHub CI                     | PARTIAL (push path works) |
| 4   | `cyclonedx-py` vs `cyclonedx-pip` CLI name           | FAKE (corrected) | Correct as-is    | N/A                           | NO (correct)              |
| 5   | `build`/`cyclonedx-bom` pins not from pyproject.toml | MEDIUM           | Code smell       | Local                         | NO                        |
| 6   | `--output-reproducible` flag unsupported             | FAKE (corrected) | Correct as-is    | N/A                           | NO (correct)              |
| 7   | Branch protection assumption unverified              | LOW              | Operational gap  | GitHub CI                     | NO                        |
| 8   | `PROVENANCE.md` not in release files                 | INFO             | Correct as-is    | N/A                           | NO                        |

---

## Distinction: Local-Only vs. GitHub CI-Required vs. Release-Runtime Evidence

| Evidence Type                                          | Examples                                                                     | Status                                                                                       |
| ------------------------------------------------------ | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **Local-only** (can be created/tested without GitHub)  | `validate-artifacts.py`, `artifacts/` dir, SBOM generation command           | 2 gaps found (findings 1,2); findings 4 and 6 were false positives (corrected by t_af933042) |
| **GitHub CI-required** (needs real GH Actions run)     | "CI" + "Security CI" workflow success, branch protection, OIDC attestation   | 1 gap found (finding 3); 1 unverified assumption (finding 7)                                 |
| **Release-runtime** (only executes on actual tag push) | Tag validation, checkout validation, artifact upload, draft release creation | Correctly structured; blocked by local gaps                                                  |

---

## Unsafe / Incorrect Workflow Assumptions

1. **Tag push skips CI gate silently.** If branch protection is misconfigured or absent, a tag push proceeds without
   CI/security verification. The workflow does not detect this condition.

2. ~~`cyclonedx-py` CLI shim may not exist~~ **(CORRECTED by t_af933042).** The `cyclonedx-bom==7.4.0` package's sole
   console entrypoint is `cyclonedx-py`. `cyclonedx-pip` does not exist. `release.yml:271` is correct.

3. **The `validate-artifacts.py` hard gate is correctly fail-closed**, but the failure message references "issue #7
   security implementation" which is accurate — the file is a cross-issue dependency.

4. ~~SBOM `--output-reproducible` flag~~ **(CORRECTED by t_af933042).** `--output-reproducible` is fully supported by
   `cyclonedx-py requirements` in cyclonedx-bom==7.4.0. No change needed.

---

## Implementation and QA Cards Created

Eight cards were created, ordered by dependency:

**CRITICAL path (must be done first):**

- `t_7a3c91f0` — **Author `scripts/validate-artifacts.py`** (dev-ops, BLOCKER for release workflow): Implement redaction
  validation per ADR-010-3 contract. Must validate SHA256SUMS.txt, sbom.cdx.json, PROVENANCE.md. Exit 0 clean, exit 1 on
  secrets. Add tests.
- `t_8b4d2c10` — **Create `artifacts/` dir and add to `.gitignore`** (dev-ops, BLOCKER for release workflow): Create
  `artifacts/` directory and add to `.gitignore` per ADR-010-3. The release workflow's `artifacts/release/` subdir is
  created dynamically by the workflow itself.

**HIGH path:**

- `t_9c5e3d21` — **Create `docs/guides/SCRIPTS_VALIDATE_ARTIFACTS_IMPLEMENTATION.md`** (dev-ops): Document the
  validate-artifacts.py implementation decisions, test approach, and redaction patterns for future maintainers.

**MEDIUM path:**

- `t_ad6f4e32` — ~~Fix `cyclonedx-pip` CLI invocation~~ **(VOIDED by t_af933042):** The `cyclonedx-pip` command does not
  exist in `cyclonedx-bom==7.4.0`. The `release.yml:271` invocation using `cyclonedx-py` is correct. This card can be
  closed as a false positive. Findings 4 and 6 in this audit were both false positives; the SBOM command in
  `release.yml` was always correct.
- `t_be7a5f43` — **Pin `build` and `cyclonedx-bom` tool versions from `pyproject.toml`** (dev-ops): Extract pinned tool
  versions from `pyproject.toml [project.optional-dependencies]` (once security tools are added per ADR-010-2) rather
  than hard-coding in release workflow.
- `t_cf8b6g54` — **Create `.github/workflows/security.yml`** (dev-ops): Implement the security CI workflow per
  ADR-010-1. Workflow name must be exactly "Security CI" to match the release prerequisite check.
- `t_d09c7h65` — **Verify branch protection ruleset for tag push CI gate** (dev-ops, operational): Document the required
  ruleset configuration. Add a validation step or comment in release.yml that fails with a clear message if branch
  protection is absent.

**LOW/QA path:**

- `t_e1a0d8i76` — **QA: Verify release workflow in isolation from clean temp venv** (dev-ops): Once all above cards are
  complete, run the release workflow against the current `v2.1.0` tag in a clean temp environment. Verify wheel build,
  smoke test, SBOM generation, artifact staging, and draft release creation.

---

## Verification Commands (Local Evidence)

```bash
# Confirm validate-artifacts.py is absent
find . -name "validate-artifacts.py"  # EXPECT: empty

# Confirm artifacts/ is absent and not gitignored
find . -type d -name "artifacts"     # EXPECT: empty
grep "artifacts" .gitignore          # EXPECT: no match

# Confirm security.yml is absent
find .github/workflows/ -name "security.yml"  # EXPECT: empty

# Confirm cyclonedx-py CLI (the ONLY CLI provided by cyclonedx-bom==7.4.0)
python -m pip install cyclonedx-bom==7.4.0
cyclonedx-py --help                 # EXPECT: usage output with commands: environment, requirements, pipenv, poetry
cyclonedx-pip --help                # EXPECT: bash: cyclonedx-pip: command not found

# Confirm cyclonedx-py requirements subcommand supports all release.yml flags
cyclonedx-py requirements --help   # EXPECT: --pyproject, --mc-type, --output-format, --output-reproducible, --output-file

# Confirm version alignment
python -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])"
# EXPECT: 2.1.0 (matches current HEAD)
```

---

## Prior Work Referenced

This analysis builds on prior triage outputs captured in the worker context:

- `t_943885de` — ADR-008 release workflow triage (source of decision record)
- `t_d322a4b9` — ADR-010 security workflow ADR (source of `validate-artifacts.py` contract)
- `t_34e724b5` — Prior gap analysis for #5/#7 (CI quality and security gates)
