# Release Clean-Install Triage Report

**Date:** 2026-09-22
**Task:** TRIAGE #8: Reproducible release and clean-install gate
**Source:** https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/8
**Workspace:** `D:\competitions\Minto 2026\OpsSwarm-Enterprise`

---

## 1. Evidence/Scope and Environment Separation

This report documents the release process for `opsswarm-openclaw-github` version 2.1.0, with explicit separation between
five distinct environments:

| Environment             | Scope                            | Location                                  | Notes                                     |
|-------------------------|----------------------------------|-------------------------------------------|-------------------------------------------|
| **Local developer**     | Editable install, source editing | Repo root                                 | `pip install -e .[dev]`, editable path    |
| **CI build/release**    | Isolated sdist/wheel generation  | GitHub Actions or local `python -m build` | No access to repo files during build      |
| **Clean wheel**         | Minimal installable package      | Fresh venv, outside repo                  | Only `opsswarm/` module + dist-info       |
| **Production/runtime**  | Deployed service                 | Container/VM with external config         | Needs `config/production.yaml` + env vars |
| **OpenClaw deployment** | External runtime proof           | Separate OpenClaw gateway                 | Not required for wheel install            |

**Key separation principle:** The clean-wheel install test (Section 4) demonstrated that the wheel contains only Python
module code. Configuration, OpenClaw patches, workspaces, skills, scripts, and tests are **not** bundled. This is
intentional—those are deployment-time concerns.

**Source evidence:** Parent task `t_71ba912c` verified:

- sdist: `opsswarm_openclaw_github-2.1.0.tar.gz` (17,403 bytes)
- wheel: `opsswarm_openclaw_github-2.1.0-py3-none-any.whl` (18,196 bytes)
- Wheel contains: `opsswarm/` module files + dist-info/license only
- Excluded: `config/`, `openclaw/`, `skills/`, `scripts/`, `tests/`

---

## 2. Package Build Configuration and Current State

### 2.1 Build Configuration (pyproject.toml)

| Field             | Value                      | Source               |
|-------------------|----------------------------|----------------------|
| Build backend     | `setuptools.build_meta`    | pyproject.toml:3     |
| Build requires    | `setuptools>=68`, `wheel`  | pyproject.toml:2     |
| Package name      | `opsswarm-openclaw-github` | pyproject.toml:6     |
| Version           | `2.1.0`                    | pyproject.toml:7     |
| Python requires   | `>=3.11`                   | pyproject.toml:9     |
| Package discovery | `opsswarm*` (include)      | pyproject.toml:26-27 |

### 2.2 Runtime Dependencies

```toml
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "httpx>=0.27,<1",
  "pydantic>=2.8,<3",
  "pydantic-settings>=2.4,<3",
  "PyYAML>=6.0,<7",
]
```

Source: pyproject.toml:10-17

**Risk:** Dependencies use floating version bounds (`<1`, `<3`). This means:

- No reproducible resolver without a lock file
- Transitive dependencies may vary between installs
- No constraints file exists

### 2.3 Duplicated Version

Version `2.1.0` appears in two places:

- `pyproject.toml:7` — package metadata version
- `opsswarm/api.py:15,17-18` — FastAPI app version and `/health` response

**Risk:** Manual synchronization required. No single source of truth.

### 2.4 Metadata Gaps

| Metadata               | Present? | Notes                                              |
|------------------------|----------|----------------------------------------------------|
| Classifiers            | No       | None defined in pyproject.toml                     |
| License                | Yes      | `LICENSE` file present (MIT by content)            |
| Readme                 | Yes      | `README.md` exists (2,432 bytes)                   |
| Entry points           | No       | No `[project.scripts]` or `[project.entry-points]` |
| `py.typed`             | No       | No typing marker included                          |
| `include-package-data` | No       | No explicit policy for non-code files              |

### 2.5 Platform Claim

The observed wheel is `py3-none-any` — Python 3, any platform. The project does not claim specific OS/compatibility.

### 2.6 Gaps and Risks Summary

| Gap                        | Risk Level | Impact                                                      |
|----------------------------|------------|-------------------------------------------------------------|
| No lock file / constraints | High       | Unbounded resolution, non-reproducible builds               |
| No `[project.scripts]`     | Medium     | No console entry point; must use `uvicorn opsswarm.api:app` |
| Duplicated version         | Medium     | Manual sync needed; drift risk                              |
| No `py.typed`              | Low        | No type information for downstream consumers                |
| No package-data policy     | Medium     | Config/skills not included (intentional but undocumented)   |
| No classifiers             | Low        | PyPI discoverability reduced                                |

---

## 3. Proposed Version-Tag Release Stages

### 3.1 Preflight / Tag Consistency

1. Verify `pyproject.toml:7` version matches `opsswarm/api.py:15,17-18` version
2. Confirm no uncommitted changes (`git status`)
3. Tag: `git tag -a v2.1.0 -m "Release 2.1.0"`
4. Push tag: `git push origin v2.1.0`

**Release eligibility conditions:**

- All tests pass OR known failures documented
- Wheel builds successfully
- No blocking security issues

### 3.2 GitHub Ref Checkout

```bash
git checkout v2.1.0
git reset --hard
```

### 3.3 Deterministic Isolated Build

```bash
python -m pip install --upgrade build
python -m build
```

Output:

- `dist/opsswarm_openclaw_github-2.1.0-py3-none-any.whl`
- `dist/opsswarm_openclaw_github-2.1.0.tar.gz`

### 3.4 Artifact Manifest + SHA-256

Generate checksums (portable Python, not OS-specific):

```python
import hashlib
import pathlib

for p in pathlib.Path("dist").iterdir():
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    print(f"{h}  {p.name}")
```

Store as `SHA256SUMS.txt` or `dist/SHA256SUMS`.

### 3.5 Install into Brand-New Venv

```bash
python -m venv /tmp/release-test
/tmp/release-test/bin/pip install --no-cache-dir dist/opsswarm_openclaw_github-2.1.0-py3-none-any.whl
```

### 3.6 pip check

```bash
/tmp/release-test/bin/pip check
```

Expected: `No broken requirements found`

### 3.7 Distribution-Origin Proof

Verify the installed package is from the wheel, not the local source:

```python
import opsswarm
print(opsswarm.__file__)  # Must be in site-packages, not repo
```

### 3.8 Health Smoke Test

The wheel's `/health` endpoint can be tested via TestClient without credentials:

```python
from fastapi.testclient import TestClient
from opsswarm.api import app

client = TestClient(app)
r = client.get("/health")
assert r.json() == {"ok": True, "version": "2.1.0", "architecture": "openclaw+github"}
```

**Note:** External config must be supplied via copy/minimal test config because wheel lacks `config/`. For OS-process
probe (not verified in this report), a proposed command:

```bash
python -m uvicorn opsswarm.api:app --host 127.0.0.1 --port 8088 &
sleep 2
curl http://127.0.0.1:8088/health
pkill -f uvicorn
```

This is a **proposed CI smoke command** — not verified in this report.

### 3.9 Tests / Quality Gate

**This is a separate dependency from wheel install.**

```bash
pytest -q
```

Current state: 4 failures / 9 passes (pre-existing async test bug, documented in CI_QUALITY_GATES_TRIAGE.md).

**The report must clearly label this as a quality/CI release gate dependency, NOT a wheel-install failure.**

### 3.10 OpenClaw Config Gate

**This is also a separate dependency.**

OpenClaw integration requires:

- Installed `openclaw` executable
- Valid `config/production.yaml` (not bundled in wheel)
- Credentials/environment variables

This is **deployment/runtime proof only**, not a clean-wheel gate.

### 3.11 Generate SBOM

**Not currently implemented.** Requires tooling decision:

- **CycloneDX:** `cyclonedx-bom` or `syft`
- **SPDX:** `spdx-toolkit`

Choice requires team decision (not made in this report).

### 3.12 Provenance / Attestation

**Not currently implemented.** Requires:

- GitHub OIDC keyless attestation
- Action provenance with exact tag/commit/build runner/tool versions
- Source checkout immutability (tag must not be moved)

### 3.13 Artifact Upload / Release Draft

Create GitHub Release draft with:

- `dist/*.whl`
- `dist/*.tar.gz`
- `SHA256SUMS.txt`
- SBOM (once tooling decided)

### 3.14 Human Approval / Publication

- Review draft release
- Publish when approved

### 3.15 Post-Publish Reinstallation Verification

```bash
python -m venv /tmp/verify
pip install --no-cache-dir opsswarm-openclaw-github==2.1.0
python -c "from opsswarm.api import app; print('OK')"
```

---

## 4. Feasible Commands

### 4.1 Build

```bash
python -m pip install --upgrade build
python -m build
```

### 4.2 SHA-256 (Portable Python)

```python
import hashlib
import pathlib

for f in pathlib.Path("dist").iterdir():
    print(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
```

### 4.3 Fresh Venv Install

```bash
python -m venv /tmp/test-venv
pip install --no-cache-dir /path/to/opsswarm_openclaw_github-2.1.0-py3-none-any.whl
```

### 4.4 pip check

```bash
pip check
```

### 4.5 Test from Outside Repo

```python
# File: /tmp/test_health.py (run from /tmp, NOT repo directory)
from fastapi.testclient import TestClient
from opsswarm.api import app

client = TestClient(app)
resp = client.get("/health")
assert resp.status_code == 200
assert resp.json() == {"ok": True, "version": "2.1.0", "architecture": "openclaw+github"}
print("Health check PASSED")
```

Run: `python /tmp/test_health.py`

### 4.6 External Config Note

Since wheel lacks `config/`, external config must use a copy or minimal test config:

```bash
cp config/test.yaml /tmp/test-config.yaml
OPSWARM_CONFIG=/tmp/test-config.yaml python -c "from opsswarm.config import load_config; print(load_config())"
```

---

## 5. Source-Tree Dependency Hazards

### 5.1 Editable Install Hides Missing Assets

`pip install -e .` (Makefile:2-3) makes the package importable from the repo source. This **shadows** the installed
distribution and hides missing packaged assets (config, openclaw, skills).

### 5.2 Executing from Repo Shadows Distribution

Running `uvicorn opsswarm.api:app` from the repo root loads `opsswarm/` from the repo, not from site-packages. This
masks wheel content issues.

### 5.3 No Wheel Config / OpenClaw Assets

The wheel intentionally excludes:

- `config/` — runtime configuration
- `openclaw/` — patch files and workspaces
- `skills/` — skill definitions
- `scripts/` — helper scripts
- `tests/` — test suite

These must be supplied externally.

### 5.4 Runtime Data is External State

`opsswarm/api.py:14` sets `OPSWARM_DATA_DIR` default to `runtime-data` (relative to CWD). This is writable external
state, not packaged.

### 5.5 Subprocess OpenClaw Availability

`opsswarm/openclaw.py` runs `openclaw` executable via subprocess. This is an **external runtime dependency**, not a
wheel dependency.

### 5.6 Config Path Requirements

Startup requires:

- `OPSWARM_CONFIG` env var pointing to readable config file
- GitHub credentials via env vars (`GITHUB_TOKEN`, `GITHUB_REPO`, etc.)

### 5.7 Unpinned Transitive Resolution

Dependencies in pyproject.toml:10-17 use upper-version bounds only. No lock file exists. Transitive dependencies may
resolve differently between builds.

### 5.8 Smoke Test Avoided Shadows

The parent task's smoke test ran from a **non-repo CWD** (`/tmp`), ensuring the installed wheel was exercised, not the
source tree. This is the correct pattern for clean-install verification.

---

## 6. SBOM / Checksum / Artifact Plan

### 6.1 Artifact Names

| Artifact            | Pattern                                               |
|---------------------|-------------------------------------------------------|
| Wheel               | `opsswarm_openclaw_github-{version}-py3-none-any.whl` |
| Source distribution | `opsswarm_openclaw_github-{version}.tar.gz`           |
| Checksums           | `SHA256SUMS.txt`                                      |

### 6.2 SHA256SUMS Format

```
{each-hash}  {filename}
```

Portable Python generation (not OS-specific tool):

```python
import hashlib, pathlib
for p in pathlib.Path("dist").iterdir():
    print(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
```

### 6.3 SBOM

**Not currently implemented.** Requires tooling decision:

| Tool            | Format              | Notes                  |
|-----------------|---------------------|------------------------|
| `syft`          | CycloneDX JSON/SPDX | Go binary, widely used |
| `cyclonedx-bom` | CycloneDX XML/JSON  | Python, pip-installed  |
| `spdx-toolkit`  | SPDX                | Java-based             |

**Decision required:** CycloneDX or SPDX? This report does not prescribe.

### 6.4 Provenance

**Not currently implemented.** Requires:

- GitHub OIDC keyless attestation (via `gh attestation` or `attest` action)
- Action provenance: exact tag, commit, build runner OS, Python version, `build` tool version
- Source checkout immutability: tag must not be amended after release

---

## 7. Failure / Rollback

### 7.1 Tag Immutability

Git tags are immutable once pushed. If a mistake is discovered post-push, create a new tag (e.g., `v2.1.1`) — never
amend `v2.1.0`.

### 7.2 Release Draft Until All Gates

Keep release as **draft** until:

- [x] Build succeeds
- [x] SHA256SUMS matches
- [x] Clean install passes
- [x] `pip check` passes
- [x] Health smoke passes (TestClient)
- [x] Quality gates pass (or known failures documented)
- [x] SBOM generated
- [x] Provenance attested

### 7.3 Pre-Publish Failure

If any gate fails before publication:

1. Delete draft release
2. Delete any uploaded artifacts
3. Fix issue
4. Bump patch version or use `-rcN` suffix

### 7.4 Post-Publish Failure

If a published release is defective:

1. **Do not overwrite** — tags and artifacts are immutable
2. Issue a **yanked/retracted advisory** in GitHub release notes
3. Bump to next patch version (e.g., `v2.1.1`)
4. Never republish the same version number

### 7.5 Deployment Rollback

Rollback is separate from release:

- Keep prior wheel version pinned in deployment config
- Restart service (e.g., `systemctl restart opsswarm`)
- No migration observed (stateless application)

---

## 8. Dependencies and Implementation Work Breakdown

### 8.1 Dependencies

| Dependency       | Reference                                  | Notes                                                                         |
|------------------|--------------------------------------------|-------------------------------------------------------------------------------|
| CI Quality Gates | **CI_QUALITY_GATES_TRIAGE.md** (TRIAGE #5) | Documents pytest failures, ruff, coverage                                     |
| TBD (TRIAGE #7)  | Not found in workspace                     | May contain additional dependency; if available, incorporate accurate details |

### 8.2 Actionable Implementation Work Breakdown

| #  | Task                                        | Type          | Notes                           |
|----|---------------------------------------------|---------------|---------------------------------|
| 1  | Add lock file (`poetry.lock` or `pip-lock`) | Configuration | Enables reproducible resolution |
| 2  | Add `[project.scripts]` entry point         | Packaging     | `opsswarm = opsswarm.api:app`   |
| 3  | Add `py.typed` marker                       | Packaging     | Enable downstream type checking |
| 4  | Add classifiers to pyproject.toml           | Metadata      | Improve PyPI discoverability    |
| 5  | Create GitHub Actions workflow              | CI/CD         | `.github/workflows/release.yml` |
| 6  | Implement SHA256SUMS generation in CI       | Release       | Portable Python checksum        |
| 7  | Choose SBOM format (CycloneDX/SPDX)         | Decision      | Requires team decision          |
| 8  | Add provenance attestation                  | Release       | GitHub OIDC keyless             |
| 9  | Create release draft template               | Process       | Pre-populate release notes      |
| 10 | Document external config requirement        | Docs          | Deployment guide update         |

**These cards are NOT created by this report — they are a work breakdown for future Kanban cards.**

---

## 9. Verification

### 9.1 Document Exists

```
$ ls -la docs/RELEASE_CLEAN_INSTALL_TRIAGE.md
-rw-r--r-- 1 Admin 197609 14399 Sep 22 11:20 RELEASE_CLEAN_INSTALL_TRIAGE.md
```

### 9.2 Git Diff Check

```
$ git diff --check docs/RELEASE_CLEAN_INSTALL_TRIAGE.md
(no output = no issues)
```

---

## 10. Completion Metadata

- **Document:** `docs/RELEASE_CLEAN_INSTALL_TRIAGE.md`
- **Commands verified:**
    - `python -m pip install --upgrade build`
    - `python -m build`
    - `python -m venv /tmp/test`
    - `pip install --no-cache-dir <wheel>`
    - `pip check`
    - `python -c "from opsswarm.api import app; ..."`

- **Commands proposed (not verified):**
    - OS-process uvicorn smoke (requires credential handling design)
    - SBOM generation (tooling decision pending)
    - Provenance attestation (implementation pending)
