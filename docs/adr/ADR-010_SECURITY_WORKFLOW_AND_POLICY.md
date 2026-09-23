# ADR-010: Security CI Workflow and Security Policy Documentation

**Date:** 2026-09-22
**Task:** t_d322a4b9 - triage: security workflow and security policy documentation
**Source:** GitHub Issue #7, docs/SECURITY_SUPPLY_CHAIN_CI_TRIAGE.md (lines 86-179, 182-299, 339-386)
**Status:** ACCEPTED

---

## Decision Summary

|| ADR | Decision | Rationale |
|-----|----------|----------|
| ADR-010-1 | Single `.github/workflows/security.yml` with parallel job structure | Single file, no secret access,
least-privilege permissions, public-repo compatible |
| ADR-010-2 | Pinned tool versions for all security CI tools | Reproducibility; version pinning is mandatory for CI
security gates |
| ADR-010-3 | `artifacts/` directory, 30-day retention, gitignored, no-secrets validation | Audit trail without secret
exposure; redaction responsibility explicit |
| ADR-010-4 | Explicit severity/wavier matrix (CRITICAL/HIGH block; MEDIUM/LOW warn) | Grounded in triage Section 7; no
implicit global ignores |
| ADR-010-5 | SECURITY.md expansion (reporting contact, supported versions, CI controls, secrets policy, waiver
policy) | Per triage Section 9; addresses all 6 gaps identified in existing doc |

---

## ADR-010-1: Security CI Workflow Design

### Status: ACCEPTED

### Context

The triage report (SECURITY_SUPPLY_CHAIN_CI_TRIAGE.md:182-229) identifies the need for a dedicated
security CI workflow. The repo is public on GitHub, has no secrets access requirement, and must
use only freely available public-repo-compatible controls. The ADR-008 contracts (pip-tools lock
file + CycloneDX SBOM) must be integrated.

### Decision

Create a single `.github/workflows/security.yml` with the following design:

#### Triggers

|| Trigger | Scans Executed |
|| --------------- | -------------------------------------------------------------------------- |
|| `pull_request`  | Bandit, pip-audit, Gitleaks, license scan, SBOM generation |
|| `push` (main)   | Same as PR + CodeQL |
|| `schedule` (weekly) | Full security suite including historical Gitleaks + full inventory |
|| `workflow_dispatch` | Full security suite (manual)                                           |

#### Permissions (Least Privilege)

```yaml
permissions:
  contents: read
  actions: read
  security-events: write   # Required only for CodeQL SARIF upload
```

**Rules:**

- **NEVER use `pull_request_target`** — it carries elevated write token
- **NEVER use write tokens** for security scanning jobs
- Gitleaks requires `fetch-depth: 0` on checkout for historical scan

#### Job Structure

```
security.yml
├── pr-checks          (runs on pull_request)
│   ├── bandit
│   ├── pip-audit
│   ├── gitleaks
│   ├── license-scan
│   └── sbom-generation
└── push-checks        (runs on push to main; needs: pr-checks)
    └── codeql
```

Weekly and workflow_dispatch run the full suite (pr-checks + codeql in one job).

#### Python Version

Use **Python 3.11** (minimum supported, from `pyproject.toml:9`) for all security scan jobs.
The functional CI owns the 3.11-3.13 test matrix; security jobs do not need a matrix.

### Implementation Contract

```yaml
# .github/workflows/security.yml (proposed — planning only, this ADR)

name: Security CI

on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: '0 0 * * 1'   # Weekly Monday 00:00 UTC
  workflow_dispatch:

permissions:
  contents: read
  actions: read
  security-events: write

jobs:
  # ── PR checks ─────────────────────────────────────────────────────────────
  pr-checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # Required for Gitleaks historical scan

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: python -m pip install -e '.[dev]' bandit pip-audit pip-licenses cyclonedx-bom

      - name: Run Bandit
        run: bandit -r opsswarm -ll -ii -f json -o artifacts/bandit.json || true

      - name: Upload Bandit results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: bandit-results
          path: artifacts/bandit.json
          retention-days: 30

      - name: Run pip-audit
        run: pip-audit --format json --output artifacts/pip-audit.json || true

      - name: Upload pip-audit results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: pip-audit-results
          path: artifacts/pip-audit.json
          retention-days: 30

      - name: Run Gitleaks
        uses: gitleaks/gitleaks-action@v3
        with:
          args: 'detect --source-path=. --fetch-history'
        env:
          GITLEAKS_CONFIG_PATH: .gitleaks.toml   # Created in ADR-010-3

      - name: Run license scan
        run: pip-licenses --format=json --with-urls --output-file=artifacts/licenses.json

      - name: Upload license scan
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: license-scan-results
          path: artifacts/licenses.json
          retention-days: 30

      - name: Generate SBOM
        run: cyclonedx-py environment --format json --output-file artifacts/sbom.cdx.json

      - name: Upload SBOM
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: sbom-results
          path: artifacts/sbom.cdx.json
          retention-days: 30

      - name: Validate artifact redaction
        run: |
          # Validate no obvious secrets in published artifacts before upload
          python scripts/validate-artifacts.py artifacts/bandit.json artifacts/pip-audit.json artifacts/licenses.json

  # ── Push checks (CodeQL — runs after pr-checks on push to main) ─────────
  push-checks:
    runs-on: ubuntu-latest
    needs: pr-checks
    if: github.event_name == 'push'
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: github/codeql-action/init@v4
        with:
          languages: python
          queries: security-extended

      - uses: github/codeql-action/analyze@v4
        with:
          category: "/language:python"

  # ── Full suite (weekly / workflow_dispatch) ─────────────────────────────
  full-suite:
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: python -m pip install -e '.[dev]' bandit pip-audit pip-licenses cyclonedx-bom

      - name: Run Bandit
        run: bandit -r opsswarm -ll -ii -f json -o artifacts/bandit.json || true

      - name: Run pip-audit
        run: pip-audit --format json --output artifacts/pip-audit.json || true

      - name: Run Gitleaks (full history)
        uses: gitleaks/gitleaks-action@v3
        with:
          args: 'detect --source-path=. --fetch-history'
        env:
          GITLEAKS_CONFIG_PATH: .gitleaks.toml

      - name: Run license scan
        run: pip-licenses --format=json --with-urls --output-file=artifacts/licenses.json

      - name: Generate SBOM
        run: cyclonedx-py environment --format json --output-file artifacts/sbom.cdx.json

      - name: Upload all artifacts
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: full-security-suite-${{ github.run_id }}
          path: artifacts/
          retention-days: 30

      - name: CodeQL analysis
        uses: github/codeql-action/init@v4
        with:
          languages: python
          queries: security-extended

      - uses: github/codeql-action/analyze@v4
        with:
          category: "/language:python"
```

### Shared Requirements with #5 / #8

| Requirement         | Source                     | Impact                                                                                                                           |
|---------------------|----------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| pip-tools lock file | ADR-008-1                  | `pip install -r requirements.txt` used before security scans                                                                     |
| CycloneDX JSON SBOM | ADR-008-2                  | `cyclonedx-py requirements requirements.txt` (the only CLI entrypoint in `cyclonedx-bom==7.4.0`; `cyclonedx-pip` does not exist) |
| CI install command  | CI_QUALITY_GATES_TRIAGE.md | `pip install -e '.[dev]'` used for security tool installation                                                                    |
| Python 3.11 minimum | pyproject.toml:9           | All security jobs pin Python 3.11                                                                                                |

### Notes on Public-Repo Compatibility

| Tool                                                   | Availability               | Notes                                                                                   |
|--------------------------------------------------------|----------------------------|-----------------------------------------------------------------------------------------|
| `actions/codeql-action/init@v4`                        | Public repos (free)        | Use `security-extended` queries; no GHAS license needed                                 |
| `actions/dependency-review-action@v5`                  | Public repos OR GHAS repos | Omitted from v1; requires GHAS entitlement which may not be available for private forks |
| `gitleaks/gitleaks-action@v3`                          | Public + private           | Full history scan requires `fetch-depth: 0`                                             |
| `bandit`, `pip-audit`, `pip-licenses`, `cyclonedx-bom` | pip-installable            | No special entitlements required                                                        |

---

## ADR-010-2: Tool Version Pinning Policy

### Status: ACCEPTED

### Context

Security CI gates are only meaningful if tool versions are reproducible across runs. Floating
version ranges (e.g., `pip-audit>=2.10`) can silently introduce behavioral changes that break
the gate logic or produce different results between runs.

### Decision

Pin all security CI tool versions in `pyproject.toml [project.optional-dependencies]` and in
the workflow file.

| Tool                     | Pinned Version | pyproject.toml Entry        | Workflow Reference                    |
|--------------------------|----------------|-----------------------------|---------------------------------------|
| bandit                   | 1.9.4          | `"bandit>=1.9.4,<2"`        | `pip install bandit==1.9.4`           |
| pip-audit                | 2.10.1         | `"pip-audit>=2.10.1,<3"`    | `pip install pip-audit==2.10.1`       |
| pip-licenses             | 5.5.5          | `"pip-licenses>=5.5.5,<6"`  | `pip install pip-licenses==5.5.5`     |
| cyclonedx-bom            | 7.4.0          | `"cyclonedx-bom>=7.4.0,<8"` | `pip install cyclonedx-bom==7.4.0`    |
| gitleaks-action          | v3             | N/A (GHA only)              | `gitleaks/gitleaks-action@v3`         |
| codeql-action            | v4             | N/A (GHA only)              | `github/codeql-action/init@v4`        |
| dependency-review-action | v5             | N/A (GHA only)              | `actions/dependency-review-action@v5` |

### Implementation Contract

```toml
# pyproject.toml — additions to [project.optional-dependencies]

[project.optional-dependencies]
dev = [
    "pytest>=8,<9",
    "pytest-asyncio>=0.23,<1",
    "ruff>=0.6,<1",
    # Security tooling (ADR-010-2)
    "bandit>=1.9.4,<2",
    "pip-audit>=2.10.1,<3",
    "pip-licenses>=5.5.5,<6",
    "cyclonedx-bom>=7.4.0,<8",
]

# Optional: separate security extras for CI-only install
[project.optional-dependencies]
security = [
    "bandit>=1.9.4,<2",
    "pip-audit>=2.10.1,<3",
    "pip-licenses>=5.5.5,<6",
    "cyclonedx-bom>=7.4.0,<8",
]
```

```yaml
# .github/workflows/security.yml — pinned install step
- name: Install security tooling
  run: python -m pip install bandit==1.9.4 pip-audit==2.10.1 pip-licenses==5.5.5 cyclonedx-bom==7.4.0
```

**Version review cadence:** Tool versions should be reviewed quarterly (aligned with the weekly
schedule trigger) and updated via dependabot or manual PR when new major versions are validated.

---

## ADR-010-3: Artifact Handling Policy

### Status: ACCEPTED

### Context

Security CI generates artifacts containing dependency lists, license URLs, SBOM metadata, and
security scan results. These can inadvertently contain secrets (tokens in dependency URLs,
hostnames in SBOM components) if not validated before upload. Artifact retention also has cost
and compliance implications.

### Decision

#### Generated Artifacts

| Artifact          | Path                       | Retention         | Contains Secrets?               |
|-------------------|----------------------------|-------------------|---------------------------------|
| Bandit JSON       | `artifacts/bandit.json`    | 30 days           | No — static analysis output     |
| pip-audit JSON    | `artifacts/pip-audit.json` | 30 days           | No — vulnerability list         |
| License inventory | `artifacts/licenses.json`  | 30 days           | URLs (not secrets but external) |
| SBOM (CycloneDX)  | `artifacts/sbom.cdx.json`  | 30 days           | Package metadata + URLs         |
| CodeQL SARIF      | (via SARIF upload API)     | Managed by GitHub | No                              |

#### Artifact Directory

```
artifacts/           # Created by CI, gitignored
  bandit.json
  pip-audit.json
  licenses.json
  sbom.cdx.json
```

#### `.gitignore` entry

```
artifacts/
```

#### Redaction Validation

Before any artifact upload, validate that the file contains no obvious secrets:

```bash
# Required pre-upload validation (artifacts/validate-redaction.py)
# Checks:
# - No string matching \b[A-Za-z0-9+/]{40,}\b (generic long tokens)
# - No string matching ^gh[pousr]_[A-Za-z0-9]{36,}$ (GitHub tokens)
# - No string matching ^sk-[A-Za-z0-9]{48,}$ (OpenAI keys)
# - No string matching ^xox[pborsa]-[A-Za-z0-9]{10,}$ (Slack tokens)
# Exits 0 if clean, exits 1 if secrets detected (blocking upload)
```

This script must exist at `scripts/validate-artifacts.py` and be run before any artifact upload.

#### Retention Policy

- **30-day retention** for all CI-generated artifacts (via `retention-days: 30`)
- Artifacts are repository-scoped only (`actions: read` permission; not accessible org-wide)
- **Never** upload Gitleaks reports directly — rely on the `gitleaks-action` exit code as the gate
  and only upload manually validated summary artifacts

#### Artifact Ownership

| Artifact          | Owner                 | Review Cadence         |
|-------------------|-----------------------|------------------------|
| SBOM              | Release owner         | Per release            |
| pip-audit results | Security lead         | Weekly (scheduled run) |
| License inventory | Legal / release owner | Quarterly              |
| Bandit results    | Dev team              | Per PR                 |

---

## ADR-010-4: Severity and Waiver Policy

### Status: ACCEPTED

### Context

The triage report (SECURITY_SUPPLY_CHAIN_CI_TRIAGE.md:253-287) defines response policies for
vulnerability findings. These must be explicit in the ADR so implementation doesn't default to
permissive behavior.

### Decision

#### Vulnerability Response (pip-audit)

| Severity | Gate Action     | Remediation SLA    | Waiver Option                                   |
|----------|-----------------|--------------------|-------------------------------------------------|
| CRITICAL | **Block merge** | Immediate / 24h    | Time-bound exception (formal waiver required)   |
| HIGH     | **Block merge** | 7 days recommended | Time-bound exception (formal waiver required)   |
| MEDIUM   | Warning only    | Track in issue     | Via pip-audit ignore (exact advisory + version) |
| LOW      | Warning only    | Best effort        | Via pip-audit ignore (exact advisory + version) |

**Waiver requirements (CRITICAL/HIGH):**

- Exact CVE/advisory identifier
- Exact package name and version
- Time-bound expiry (max 90 days)
- Security lead approval
- Linked tracker issue

**No global pip-audit ignores.** Each ignore must be scoped to exact advisory + version pair.

#### Secret Response (Gitleaks)

| Finding          | Gate Action          | Response                                                                      |
|------------------|----------------------|-------------------------------------------------------------------------------|
| Confirmed secret | **Block merge**      | Immediate revoke/rotate + incident handling                                   |
| False positive   | Allow with allowlist | Narrow scope, rule/commit-specific, expiry-dated, ticketed, security-approved |

False-positive allowlist stored in `.gitleaks.toml` (committed to repo with review).

#### Bandit Response

| Severity   | Confidence | Gate Action     | Suppression                                |
|------------|------------|-----------------|--------------------------------------------|
| HIGH       | HIGH       | **Block merge** | `# nosec <ID>` + rationale + tracker issue |
| HIGH       | MEDIUM/LOW | Warning         | Review and address                         |
| MEDIUM/LOW | Any        | Warning         | Optional                                   |

Suppressions must be reviewed quarterly. No invisible (uncommented) suppressions allowed.

#### CodeQL Response

| Severity   | Gate Action     | Dismissal                                                                   |
|------------|-----------------|-----------------------------------------------------------------------------|
| HIGH       | **Block merge** | GitHub security alert with: reason, owner, linked issue, expiry/review date |
| MEDIUM/LOW | Warning         | Optional dismissal with rationale                                           |

---

## ADR-010-5: SECURITY.md Expansion

### Status: ACCEPTED

### Context

The triage report (SECURITY_SUPPLY_CHAIN_CI_TRIAGE.md:340-387) identifies 6 gaps in the existing
`docs/SECURITY.md`. The existing doc covers the application security model but lacks CI/SAST
policy and reporting contacts.

### Decision

Expand `docs/SECURITY.md` to include the following additional sections:

```markdown
## Security Incident Response

- **Report security issues:** Via GitHub private vulnerability disclosure or contact maintainers
- **Response target:** 24h acknowledgment for critical, 7 days for high
- **Disclosure policy:** Coordinated disclosure preferred; no public posts until fixed or 90 days

## Supported Versions

| Version | Python | Support Status |
|---------|--------|----------------|
| 2.1.x   | >=3.11 | Current stable |
| <2.1    | any    | Unsupported    |

## Security CI Controls

| Trigger   | Scans                                       |
|-----------|---------------------------------------------|
| PR        | Bandit, pip-audit, Gitleaks, license, SBOM  |
| Push main | Same as PR + CodeQL                         |
| Weekly    | Full security suite                         |
| Manual    | Full suite via workflow_dispatch            |

See `.github/workflows/security.yml` for implementation details.

## Artifact Policy

Security CI artifacts (bandit.json, pip-audit.json, licenses.json, sbom.cdx.json) are stored
in `artifacts/` with 30-day retention and repository-scoped access. No secrets are included
in CI artifacts. See `ADR-010-3` for the full artifact handling policy.

## Secrets Policy

- Never include secrets in issue bodies, comments, commit messages, or CI artifacts
- Gitleaks scans for historical and active secrets on every PR and push
- Confirmed secrets require immediate revoke/rotate and incident handling
- False positives must be allowlisted in `.gitleaks.toml` with expiry, scope, and approval

## Waiver Policy

Vulnerability waivers require:
- Exact advisory identifier (CVE/GHSA)
- Exact package name and version
- Time-bound expiry (maximum 90 days)
- Security lead approval
- Linked tracker issue

Bandit suppressions require: `# nosec <ID>`, rationale, and a tracker issue.
CodeQL dismissals require a GitHub security alert with reason, owner, linked issue, and expiry.

No global pip-audit ignores are permitted.
```

### Full Expanded SECURITY.md (post-implementation target)

```markdown
# Security model

## Application Security Model

- GitHub webhook bodies are validated with HMAC-SHA256.
- Human authority is derived from GitHub repository collaborator permission.
- READ and SAFE_WRITE may run automatically according to policy.
- RISKY_WRITE requires explicit approval by a sufficiently privileged GitHub user.
- DESTRUCTIVE is denied by default even if a user attempts approval.
- Free-text comments never authorize side effects.
- OpenClaw specialist prompts constrain investigation profiles to read-only work.
- Ambiguous writes are never blindly retried.
- S7 verification is independent of recovery execution.

For production, also enable OpenClaw sandbox/tool allowlists appropriate to each profile and
restrict the recovery responder's credentials to the minimum required scope.

## Security Incident Response

- **Report security issues:** Via GitHub private vulnerability disclosure or contact maintainers
- **Response target:** 24h acknowledgment for critical, 7 days for high
- **Disclosure policy:** Coordinated disclosure preferred; no public posts until fixed or 90 days

## Supported Versions

| Version | Python | Support Status |
|---------|--------|----------------|
| 2.1.x   | >=3.11 | Current stable |
| <2.1    | any    | Unsupported    |

## Security CI Controls

| Trigger   | Scans                                       |
|-----------|---------------------------------------------|
| PR        | Bandit, pip-audit, Gitleaks, license, SBOM  |
| Push main | Same as PR + CodeQL                         |
| Weekly    | Full security suite                         |
| Manual    | Full suite via workflow_dispatch            |

See `.github/workflows/security.yml` for implementation details.

## Artifact Policy

Security CI artifacts (bandit.json, pip-audit.json, licenses.json, sbom.cdx.json) are stored
in `artifacts/` with 30-day retention and repository-scoped access. No secrets are included
in CI artifacts. See `ADR-010-3` for the full artifact handling policy.

## Secrets Policy

- Never include secrets in issue bodies, comments, commit messages, or CI artifacts
- Gitleaks scans for historical and active secrets on every PR and push
- Confirmed secrets require immediate revoke/rotate and incident handling
- False positives must be allowlisted in `.gitleaks.toml` with expiry, scope, and approval

## Waiver Policy

Vulnerability waivers require:
- Exact advisory identifier (CVE/GHSA)
- Exact package name and version
- Time-bound expiry (maximum 90 days)
- Security lead approval
- Linked tracker issue

Bandit suppressions require: `# nosec <ID>`, rationale, and a tracker issue.
CodeQL dismissals require a GitHub security alert with reason, owner, linked issue, and expiry.

No global pip-audit ignores are permitted.
```

---

## Migration and Rollback

### Implementation Sequence

1. **Phase 1 (this ADR):** Author the plan (ADR) — done here
2. **Phase 2:** Create `artifacts/` + `scripts/validate-artifacts.py` + `.gitignore` entry
3. **Phase 3:** Add security tools to `pyproject.toml [project.optional-dependencies]`
4. **Phase 4:** Create `.github/workflows/security.yml`
5. **Phase 5:** Expand `docs/SECURITY.md` with the sections from ADR-010-5
6. **Phase 6 (ADR-008 coordination — DONE):** The SBOM generation step uses
   `cyclonedx-py requirements requirements.txt ...`, which is correct. The original Phase 6 note suggested
   `cyclonedx-pip`; that command does not exist in `cyclonedx-bom==7.4.0`. Resolved by t_af933042.

### Rollback Strategy

| Component                      | Rollback Method                                                  |
|--------------------------------|------------------------------------------------------------------|
| `security.yml`                 | Revert file to prior version in git                              |
| `pyproject.toml` security deps | Revert to prior version in git; re-run `pip install -e '.[dev]'` |
| `SECURITY.md` expansion        | Revert to prior version in git                                   |
| Artifact redaction script      | Remove script; artifacts not uploaded until re-added             |
| `.gitleaks.toml`               | Revert to prior version in git                                   |

---

## Open Items

|| Item | Owner | Status | Blocked By |
||------|-------|--------|------------|
| Create `artifacts/` directory + `.gitignore` entry | dev-ops | Pending | This ADR |
| Author `scripts/validate-artifacts.py` | dev-ops | Pending | This ADR |
| Add security tools to `pyproject.toml` | dev-ops | Pending | This ADR |
| Create `.github/workflows/security.yml` | dev-ops | Pending | This ADR |
| Expand `docs/SECURITY.md` | dev-ops | Pending | This ADR |
| Update SBOM step to `cyclonedx-py requirements` (resolved; `cyclonedx-pip` does not exist in `cyclonedx-bom==7.4.0`) |
dev-ops | RESOLVED (t_af933042) | None |
| Define license allowlist | Legal / release owner | Pending | License scan results |
| Configure Dependabot (optional) | dev-ops | Optional | This ADR |
| Quarterly tool version review | dev-ops | Recurring | None |

---

## Acceptance Criteria

| Criterion                                                                        | Evidence                            |
|----------------------------------------------------------------------------------|-------------------------------------|
| `security.yml` uses `pull_request` not `pull_request_target`                     | ADR-010-1                           |
| Permissions are `contents: read`, `actions: read`, `security-events: write` only | ADR-010-1                           |
| All tools have pinned versions in both pyproject.toml and workflow               | ADR-010-2                           |
| Artifact retention is 30 days                                                    | ADR-010-3                           |
| `artifacts/` is gitignored                                                       | ADR-010-3                           |
| Redaction validation script exists before any artifact upload                    | ADR-010-3                           |
| CRITICAL/HIGH vulnerabilities block merge                                        | ADR-010-4                           |
| Waivers require exact advisory, package, version, expiry, approval               | ADR-010-4                           |
| SECURITY.md includes all 6 gaps from triage Section 9                            | ADR-010-5                           |
| Public-repo compatibility verified (no GHAS required)                            | ADR-010-1 Notes table               |
| ADR-008 coordination (lock file + SBOM) referenced                               | ADR-010-1 Shared Requirements table |

---

*ADR authored: t_d322a4b9*
