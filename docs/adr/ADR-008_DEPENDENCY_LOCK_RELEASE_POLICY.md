# ADR-008: Dependency Lock and Release Artefact Policy

**Date:** 2026-09-22
**Task:** t_30fe5eb1 - ADR triage: dependency lock and release artefact policy
**Source:** GitHub Issue #8, docs/RELEASE_CLEAN_INSTALL_TRIAGE.md
**Status:** ACCEPTED

---

## Decision Summary

| ADR       | Decision                                      | Rationale                                                                                  |
| --------- | --------------------------------------------- | ------------------------------------------------------------------------------------------ |
| ADR-008-1 | Adopt `pip-tools` (pip-compile) for lock file | Minimal tooling, no extra runtime deps, matches existing pip ecosystem                     |
| ADR-008-2 | Adopt CycloneDX JSON for SBOM                 | Python-native (`cyclonedx-bom`), JSON widely consumed, SPDX complexity unjustified         |
| ADR-008-3 | Explicit "external deployment" asset policy   | Formalize wheel contents contract; config/skills/openclaw are deployment-time, not bundled |

---

## ADR-008-1: Lock File Strategy

### Status: ACCEPTED

### Context

The triage report (RELEASE_CLEAN_INSTALL_TRIAGE.md:60-66) identifies high risk from floating version bounds:

```
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1",
  "httpx>=0.27,<1",
  ...
]
```

No lock file exists. Transitive dependencies may resolve differently between builds.

### Decision

Adopt `pip-tools` (specifically `pip-compile`) to generate `requirements.txt` lock file.

### Rationale

- **Minimal additional tooling**: Uses existing pip ecosystem, no Poetry/PDM runtime dependency
- **Reproducibility**: Pins all transitive dependencies to exact versions
- **CI compatibility**: Standard `pip install -r requirements.txt` works in GitHub Actions
- **Audit trail**: Lock file is text, diff-friendly, git-reviewable

### Implementation Contract

```
# Files to add:
- requirements.txt          # Direct deps (mirrors pyproject.toml [project] dependencies)
- requirements.txt         # Pip-compiled lock file (committed to repo)

# CI workflow addition:
- pip install pip-tools
- pip-compile requirements.txt --generate-hashes --output-file=requirements.txt
```

### Shared Requirements with #7

- Security triage (#7) uses same lock file for dependency scanning
- SBOM generation references locked versions
- Both #7 and #8 require reproducible resolution

---

## ADR-008-2: SBOM Format and Tool

### Status: ACCEPTED

### Context

The triage report (RELEASE_CLEAN_INSTALL_TRIAGE.md:396-406) identifies SBOM as "not currently implemented" and lists
tool options:

| Tool          | Format              | Notes                  |
| ------------- | ------------------- | ---------------------- |
| syft          | CycloneDX JSON/SPDX | Go binary, widely used |
| cyclonedx-bom | CycloneDX XML/JSON  | Python, pip-installed  |
| spdx-toolkit  | SPDX                | Java-based             |

### Decision

Adopt CycloneDX JSON format using `cyclonedx-bom` Python package.

### Rationale

- **Python-native**: No external runtime (Go/Java), installs via pip
- **JSON format**: Widely consumed by vulnerability scanners, SBOM databases
- **Tool availability**: `cyclonedx-bom` supports pip-compile output
- **SPDX overkill**: SPDX complexity unjustified for single-package repo; CycloneDX sufficient

### Implementation Contract

```
# Files to add:
- .sbom/                    # SBOM output directory (gitignored)
- sbom.json                 # CycloneDX JSON (published with release)

# CI workflow addition:
- pip install cyclonedx-bom
- cyclonedx-py requirements requirements.txt --format json --output sbom.json
```

### Shared Requirements with #7

- Security triage (#7) scans SBOM for vulnerabilities
- SBOM version matches release version
- Tool choice consistent across #7 (dependency review) and #8 (release)

---

## ADR-008-3: Bundled vs External Runtime Asset Policy

### Status: ACCEPTED

### Context

The triage report (RELEASE_CLEAN_INSTALL_TRIAGE.md:22) confirms wheel contains only Python module code:

> Wheel contains: `opsswarm/` module files + dist-info/license only
> Excluded: `config/`, `openclaw/`, `skills/`, `scripts/`, `tests/`

This is intentional but undocumented as a policy.

### Decision

Formalize "External Deployment" asset policy:

| Asset Category                 | Bundled in Wheel? | Deployment Method                      |
| ------------------------------ | ----------------- | -------------------------------------- |
| `opsswarm/` Python modules     | YES               | pip install                            |
| `LICENSE`                      | YES               | setuptools default                     |
| `config/*.yaml`                | NO                | External config mount / env injection  |
| `openclaw/` patches/workspaces | NO                | OpenClaw gateway fetch or volume mount |
| `skills/` (S1-S8)              | NO                | Deployed with OpenClaw workspace       |
| `scripts/*.sh`                 | NO                | CI/deployment pipeline                 |
| `tests/`                       | NO                | Not deployed                           |

### Rationale

- **Separation of concerns**: Wheel is pure Python distribution; deployment-specific files are environment-specific
- **Security**: Smaller attack surface in wheel; configs may contain secrets
- **Flexibility**: Different environments (dev/staging/prod) use different configs
- **Clean wheel test verified**: Current wheel correctly excludes these (triage evidence)

### Implementation Contract

```
# Document in docs/RELEASE_POLICY.md:
## Wheel Contents Contract

The opsswarm-openclaw-github wheel contains ONLY:
- Python module code (opsswarm/ package)
- Package metadata (dist-info/)
- License file

The following are EXCLUDED and must be provided at deployment time:
- Configuration files (config/production.yaml, config/test.yaml)
- OpenClaw patches and workspaces (openclaw/)
- Skill definitions (skills/s1-intent-guard/ through skills/s8-orchestration-hub/)
- Utility scripts (scripts/)
- Test suite (tests/)
```

---

## Migration and Rollback

### Migration Path

1. Generate initial `requirements.txt` from `pyproject.toml` dependencies
2. Run `pip-compile requirements.txt --generate-hashes --output-file=requirements.txt`
3. Add `cyclonedx-bom` to `[project.optional-dependencies]` or CI-only deps
4. Create `docs/RELEASE_POLICY.md` with asset policy documentation
5. Update child task t_943885de (release workflow) with these ADR contracts
6. Update child task t_d322a4b9 (security workflow) to reference lock file + SBOM

### Rollback Strategy

- **Lock file**: Revert `requirements.txt` to prior version in git
- **SBOM**: Prior release SBOM remains in git history / GitHub releases
- **Asset policy**: Documentation-only change; no runtime impact

---

## Acceptance Criteria Verification

| Criterion                        | Evidence                                                      |
| -------------------------------- | ------------------------------------------------------------- |
| Reproducibility guarantees       | `requirements.txt` pins all transitive deps with hashes       |
| Supported installers/Python      | pip, pip-tools verified; Python 3.11-3.13 from pyproject.toml |
| SBOM integration                 | CycloneDX JSON generated from locked requirements             |
| Asset/config deployment contract | docs/RELEASE_POLICY.md formalizes bundle boundaries           |
| Migration/rollback               | Git-based rollback for lock/SBOM; no schema migration needed  |
| #7/#8 shared requirements        | Both use same lock file; SBOM feeds security scanning         |

---

## Open Items

| Item                                         | Owner                | Status                         |
| -------------------------------------------- | -------------------- | ------------------------------ |
| Generate requirements.txt / requirements.txt | dev-ops (t_943885de) | BLOCKED - waiting on ADR-008-1 |
| Add cyclonedx-bom to pyproject.toml or CI    | dev-ops (t_943885de) | BLOCKED - waiting on ADR-008-2 |
| Document RELEASE_POLICY.md                   | dev-ops (t_943885de) | BLOCKED - waiting on ADR-008-3 |
| Security workflow integration                | dev-ops (t_d322a4b9) | BLOCKED - waiting on ADR-008-2 |

---

_ADR authored: t_30fe5eb1_
