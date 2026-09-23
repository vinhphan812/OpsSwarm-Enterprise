# Security and Supply-Chain CI Gate Triage Report

**Date:** 2026-09-22
**Task:** TRIAGE #7: Author security and supply-chain CI gate report
**Source:** https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/7
**Workspace:** `D:\competitions\Minto 2026\OpsSwarm-Enterprise`

---

## 1. Executive Summary

This document specifies the minimum viable security and supply-chain CI workflow for OpsSwarm Enterprise.
**No workflow, configuration, or documentation files are modified.** The report is the deliverable.
All changes are proposed (not implemented) and clearly labeled as such.

---

## 2. Source-Backed Findings

### 2.1 Python Version Support

`pyproject.toml:9` declares `requires-python = ">=3.11"`

| Component            | Version                                                      | Source                 |
|----------------------|--------------------------------------------------------------|------------------------|
| Python minimum       | 3.11                                                         | `pyproject.toml:9`     |
| Runtime dependencies | FastAPI, uvicorn, httpx, pydantic, pydantic-settings, PyYAML | `pyproject.toml:10-17` |
| Dev dependencies     | pytest, pytest-asyncio, ruff                                 | `pyproject.toml:20`    |
| Build backend        | setuptools 68+                                               | `pyproject.toml:2`     |

### 2.2 Current Security Model

`docs/SECURITY.md:3-13` documents:

- GitHub webhook bodies validated with HMAC-SHA256
- Human authority derived from GitHub collaborator permission
- READ/SAFE_WRITE auto-run based on policy
- RISKY_WRITE requires explicit approval
- DESTRUCTIVE denied by default
- Free-text comments never authorize side effects
- OpenClaw specialist prompts constrain to read-only

### 2.3 Environment Variable Security

| Variable                | Usage                       | Source                  |
|-------------------------|-----------------------------|-------------------------|
| `GITHUB_TOKEN`          | Bearer token for GitHub API | `opsswarm/api.py:12`    |
| `GITHUB_REPO`           | Repository identifier       | `opsswarm/api.py:12`    |
| `GITHUB_WEBHOOK_SECRET` | HMAC validation             | `opsswarm/api.py:37-38` |
| `OPSWARM_OPENCLAW_*`    | OpenClaw configuration      | `opsswarm/api.py:13-14` |

Webhook signature validation is implemented in `opsswarm/webhook.py:4-8`:

```python
def verify_signature(secret:str,body:bytes,signature:str|None)->bool:
    if not secret: return False
    if not signature or not signature.startswith("sha256="): return False
    expected="sha256="+hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)
```

GitHub client token handling: `opsswarm/github_client.py:9`

```python
"Authorization":f"Bearer {token}"
```

### 2.4 Environment Configuration

`.env.example` contains placeholder values:

- `GITHUB_TOKEN=github_pat_xxx`
- `GITHUB_REPO=owner/repository`
- `GITHUB_WEBHOOK_SECRET=change-me`

`.gitignore:5` ignores `.env` files to prevent accidental secrets commit.

### 2.5 Lockfile Status

**Finding:** The repository currently has **no lockfile** (no `requirements.txt`, `poetry.lock`, or `pip-lock`).

- Implication: SBOM precision is weaker; reproducibility depends on loose version ranges
- Recommendation: Separate follow-up to choose a lock strategy (out of scope for this triage)

---

## 3. Tool Compatibility Verification

| Tool          | Min Version | Python Requirement | Compatibility      |
|---------------|-------------|--------------------|--------------------|
| bandit        | 1.9.4       | >=3.10             | ✓ Python 3.11-3.13 |
| pip-audit     | 2.10.1      | >=3.10             | ✓ Python 3.11-3.13 |
| cyclonedx-bom | 7.4.0       | >=3.9,<4           | ✓ Python 3.11-3.13 |
| pip-licenses  | 5.5.5       | >=3.9              | ✓ Python 3.11-3.13 |

---

## 4. Proposed Tool Commands

### 4.1 Static Analysis (Bandit)

```bash
bandit -r opsswarm -ll -ii -f json -o artifacts/bandit.json
```

- `-ll`: High severity only
- `-ii`: High confidence only
- `-f json`: JSON output for parsing
- Gate: **Block merge on HIGH severity / HIGH confidence findings**

### 4.2 Dependency Audit (pip-audit)

```bash
# After: python -m pip install -e '.[dev]'
pip-audit --format json --output artifacts/pip-audit.json
```

- Gate: **Block merge on ANY vulnerability (high/critical required, low/medium must have waiver)**
- Zero exit code = pass; non-zero = vulnerability found

### 4.3 SBOM Generation (CycloneDX)

```bash
cyclonedx-py environment <venv> --of JSON -o artifacts/sbom.cdx.json
```

- Generates CycloneDX JSON SBOM for software bill of materials
- Used for supply-chain transparency and vulnerability lookup

### 4.4 License Inventory

```bash
pip-licenses --format=json --with-urls --output-file=artifacts/licenses.json
```

- Generates license inventory for compliance review
- Gate: **Generate inventory first, define allowlist after counsel review** (see Section 7)

### 4.5 CodeQL Analysis

```yaml
# Actions YAML (proposed)
- uses: github/codeql-action/init@v4
  with:
       languages: python
       queries: security-extended
- uses: github/codeql-action/analyze@v4
```

- Requires: GitHub Code Security entitlement for private/internal repos
- Schedule: PR, push to main, weekly dispatch
- Gate: **Block merge on HIGH severity findings**

### 4.6 Secret Scanning (Gitleaks)

```yaml
# Actions YAML (proposed)
- uses: gitleaks/gitleaks-action@v3
  with:
       args: detect --source-path=. --fetch-history
```

- Requires: `fetch-depth: 0` on checkout for historical scan
- Gate: **Block merge on any confirmed secret**
- False positives: narrow rule/commit scoped allowlist with expiry, ticket, security approval

### 4.7 Dependency Review Action

```yaml
# Actions YAML (proposed)
- uses: actions/dependency-review-action@v5
  with:
       fail-on-severity: high
       allow-licenses: MIT, Apache-2.0, BSD-3-Clause
```

- Availability: Public repos OR organization private repos with GHAS
- Scope: **Newly introduced dependency changes only** (PR diff)
- Limitation: Cannot replace scheduled pip-audit (see Section 5.2)

---

## 5. Proposed CI Workflow Design

### 5.1 Single Workflow File

**Proposed file:** `.github/workflows/security.yml`

### 5.2 Triggers

| Trigger         | Scans Executed                                                          |
|-----------------|-------------------------------------------------------------------------|
| PR (to main)    | Dependency Review (if GHAS), Gitleaks, Bandit, pip-audit, License, SBOM |
| Push (to main)  | Same as PR + CodeQL                                                     |
| Weekly schedule | CodeQL, pip-audit, Gitleaks (historical), full inventory/SBOM           |
| Manual dispatch | Full security suite                                                     |

### 5.3 Permissions (Least Privilege)

```yaml
permissions:
     contents: read
     actions: read
     security-events: write
```

- **DO NOT use `pull_request_target`** (elevated privileges)
- **DO NOT use write tokens** for security scanning jobs
- Security results require `security-events: write` only for CodeQL SARIF upload

### 5.4 Python Version for Security Jobs

- Use **Python 3.11** (minimum supported) for security scans
- Functional CI owns the 3.11-3.13 matrix; security jobs don't need matrix

### 5.5 Job Dependencies

```
security.yml
├── pr-checks
│   ├── dependency-review (if GHAS)
│   ├── gitleaks
│   ├── bandit
│   ├── pip-audit
│   ├── license-scan
│   └── sbom-generation
└── push-checks (needs: pr-checks)
    └── codeql
```

---

## 6. Artifact Management

### 6.1 Generated Artifacts

| Artifact          | Path                       | Retention | Notes                    |
|-------------------|----------------------------|-----------|--------------------------|
| Bandit JSON       | `artifacts/bandit.json`    | 30 days   | Exclude secrets          |
| pip-audit JSON    | `artifacts/pip-audit.json` | 30 days   | Exclude secrets          |
| License inventory | `artifacts/licenses.json`  | 30 days   | May contain URLs         |
| SBOM (CycloneDX)  | `artifacts/sbom.cdx.json`  | 30 days   | Supply-chain metadata    |
| CodeQL SARIF      | `artifacts/codeql.sarif`   | 30 days   | Via actions/upload-sarif |

### 6.2 Artifact Security

- **Never upload secret-bearing reports** as workflow artifacts
- All security artifacts should have least access (same repository only)
- Gitleaks reports: validate no secrets before upload

---

## 7. Severity and Waiver Policy Matrix

### 7.1 Vulnerability Response

| Severity | Gate Action     | Remediation SLA    | Waiver Option                                 |
|----------|-----------------|--------------------|-----------------------------------------------|
| CRITICAL | **Block merge** | Immediate / 24h    | Time-bound exception (formal waiver required) |
| HIGH     | **Block merge** | 7 days recommended | Time-bound exception (formal waiver required) |
| MEDIUM   | Warning only    | Track in issue     | Via pip-audit ignore (exact advisory+version) |
| LOW      | Warning only    | Best effort        | Via pip-audit ignore (exact advisory+version) |

### 7.2 Secret Response

| Finding          | Gate Action          | Response                                                                      |
|------------------|----------------------|-------------------------------------------------------------------------------|
| Confirmed secret | **Block merge**      | Immediate revoke/rotate + incident handling                                   |
| False positive   | Allow with allowlist | Narrow scope, rule/commit specific, expiry-dated, ticketed, security approved |

### 7.3 Bandit Response

| Severity   | Confidence | Gate Action     | Suppression                          |
|------------|------------|-----------------|--------------------------------------|
| HIGH       | HIGH       | **Block merge** | `# nosec <ID>` + rationale + tracker |
| HIGH       | MEDIUM/LOW | Warning         | Review and address                   |
| MEDIUM/LOW | Any        | Warning         | Optional                             |

- Suppressions must be reviewed periodically
- No invisible suppressions allowed

### 7.4 CodeQL Response

| Severity   | Gate Action     | Dismissal                                                                  |
|------------|-----------------|----------------------------------------------------------------------------|
| HIGH       | **Block merge** | GitHub security alert with reason, owner, linked issue, expiry/review date |
| MEDIUM/LOW | Warning         | Optional dismissal with rationale                                          |

### 7.5 License Policy

| License Status                        | Gate Action                             |
|---------------------------------------|-----------------------------------------|
| Allowlisted (MIT, Apache-2.0, BSD-\*) | Pass                                    |
| Unknown                               | **Block for release** until adjudicated |
| Noassertion                           | **Block for release** until adjudicated |
| Copyleft (GPL-\*)                     | Warning only (review for compatibility) |

- **Initial policy:** Generate inventory, define allowlist after counsel/release owner review
- Do not falsely block at first pass

---

## 8. Ownership and Follow-up Tasks

### 8.1 Immediate Owners

| Area                       | Owner                 | Notes                         |
|----------------------------|-----------------------|-------------------------------|
| Security CI implementation | DevOps / Security     | Create security.yml           |
| Dependency management      | Dev team              | Choose lock strategy          |
| License policy             | Legal / Release owner | Define allowlist              |
| Waiver审批                   | Security lead         | Approve time-bound exceptions |

### 8.2 Bounded Follow-up Tasks

| #  | Task                                       | Bounded By                | Owner      |
|----|--------------------------------------------|---------------------------|------------|
| F1 | Implement `.github/workflows/security.yml` | This triage               | DevOps     |
| F2 | Choose lock strategy (pip/poetry/uv)       | This triage               | Dev team   |
| F3 | Define license allowlist                   | F1 + inventory generation | Legal      |
| F4 | Configure Dependabot (optional)            | This triage               | Dev team   |
| F5 | Expand docs/SECURITY.md (see Section 9)    | This triage               | Docs owner |

### 8.3 Validation Commands

```bash
# Local validation (after implementation)
bandit -r opsswarm -ll -ii -f json -o artifacts/bandit.json
echo "Bandit exit code: $?"

python -m pip install -e '.[dev]'
pip-audit --format json --output artifacts/pip-audit.json
echo "pip-audit exit code: $?"

pip-licenses --format=json --with-urls --output-file=artifacts/licenses.json
```

---

## 9. Documentation Delta: SECURITY.md Expansion

**Current state:** `docs/SECURITY.md` lacks:

1. **Reporting contact/response target** — who to contact for security issues
2. **Supported versions** — currently 2.1.x / Python >=3.11 (until policy adopted)
3. **Security CI controls and scopes** — what scans run, when
4. **Disclosure/triage** — how to report vulnerabilities
5. **Explicit no-secrets policy** — no secrets in issue bodies/logs/artifacts
6. **Remediation and waiver policy** — how exceptions are handled

**Proposed additions to docs/SECURITY.md:**

```markdown
## Security Incident Response

- **Report security issues:** Via GitHub private vulnerability disclosure or contact maintainers
- **Response target:** 24h acknowledgment for critical, 7 days for high

## Supported Versions

| Version | Python | Support Status |
| ------- | ------ | -------------- |
| 2.1.x   | >=3.11 | Current stable |

## Security CI Controls

| Trigger   | Scans                                      |
| --------- | ------------------------------------------ |
| PR        | bandit, pip-audit, gitleaks, license, SBOM |
| Push main | Same + CodeQL                              |
| Weekly    | Full suite                                 |

See `.github/workflows/security.yml` for implementation.

## Secrets Policy

- Never include secrets in issue bodies, comments, or CI artifacts
- Gitleaks scans for historical and active secrets
- Confirmed secrets require immediate revoke/rotate

## Waiver Policy

- Vulnerability waivers require: exact advisory, package, version, time-bound expiry, security approval
- No global pip-audit ignores
- Bandit suppressions require: `# nosec <ID>`, rationale, tracker issue
- CodeQL dismissals via GitHub security alert with reason, owner, linked issue, expiry
```

---

## 10. Summary

| Category                | Status                                            |
|-------------------------|---------------------------------------------------|
| Tool compatibility      | ✓ Verified for Python 3.11-3.13                   |
| Lockfile                | ✗ None present (recommend F2 follow-up)           |
| Existing security model | ✓ HMAC, collaborator authority, approval controls |
| CI workflow             | Proposed (not implemented)                        |
| Artifact plan           | Defined                                           |
| Severity matrix         | Defined                                           |
| Waiver policy           | Defined                                           |
| Documentation delta     | Proposed                                          |

---

## 11. Git Diff Check

```bash
$ git diff --check
# (no output = no staged changes to existing files)
```

**Result:** No modifications to existing files. Report is new untracked file only.

---

## 12. Acceptance Criteria Verification

- [x] Cite concrete source paths/lines
- [x] Include tool-command table (Section 4)
- [x] Include workflow/job/trigger/permission plan (Section 5)
- [x] Include artifacts table (Section 6)
- [x] Include severity/waiver matrix (Section 7)
- [x] Include ownership with bounded follow-up tasks (Section 8)
- [x] Include validation commands (Section 8.3)
- [x] Label all proposed changes as proposed
- [x] Run `git diff --check` — no output (no existing file modifications)
- [x] Do not alter files outside the report
