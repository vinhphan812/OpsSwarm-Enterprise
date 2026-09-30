# Security model

## Error handling and sanitisation

OpsSwarm follows a **fail-closed, sanitize-always** policy for all operator-facing
output.

### Correlation IDs
Every exception that surfaces at the API or orchestrator layer is assigned a short
correlation ID (12-character hex). The ID appears in both:
- Operator logs (at ERROR level, with the redacted error detail)
- GitHub comments (at the end of the failure message, preceded by "Ref: ")

Operators can grep server-side logs by the correlation ID to retrieve the full
redacted trace without secrets appearing in the GitHub issue.

### GitHub comment sanitisation
Raw exception text, OpenClaw stderr, Pydantic validation error details, file
paths, and any token (GitHub PAT, Bearer token, AWS key, `secret=`/`password=`
values in JSON) are stripped before text reaches a GitHub comment. The only
content that ever appears in a comment is:

- A fixed failure banner ("OpsSwarm — Failed / Recovery failed / Verification failed")
- A sanitised summary (category, not raw content)
- The correlation ID

Specifically:
- `api.py` webhook handler: `PermissionError` and generic `Exception` are caught;
  the raw message is never posted — only a correlation ID + fixed string.
- `orchestrator.py` failure paths: `run.error` reason and `run.execution.summary`
  are passed through `sanitize_for_comment()` before being embedded in a comment.
- `openclaw.py` `run_text()`: non-zero exit code raises `OpenClawErrorSanitized`
  with sanitised stderr. The raw stderr is logged at ERROR level (redacted for
  tokens only; paths are preserved for operator use).

### Log redaction
Operator logs use `sanitize_for_log()`, which redacts tokens and auth headers but
preserves file paths so operators can still correlate errors. Logs are the only
place where file paths from OpenClaw subprocesses are retained.

### Secret pre-flight
`verify_api_key()` uses `hmac.compare_digest()` for constant-time comparison to
mitigate timing attacks.

### Runtime API authentication (Issue #21)

The Runtime API (`opsswarm/api.py`) enforces scoped bearer-token authentication for all
endpoints except `/health`. Authentication is implemented in `opsswarm/auth.py`.

**Scopes**

| Scope | Endpoints |
|-------|-----------|
| `opsswarm:read` | `GET /runs`, `GET /runs/{issue_number}`, `GET /runs/{issue_number}/evidence`, `GET /runs/{issue_number}/checkpoint` |
| `opsswarm:write` | `POST /runs/{issue_number}/resume` |
| `opsswarm:monitor` | `POST /hooks/monitoring` (also requires HMAC webhook signature) |
| `opsswarm:admin` | All above + `GET /metrics` |

Scope hierarchy: `opsswarm:admin` implies all other scopes. `opsswarm:write` and
`opsswarm:monitor` do not imply read access.

**Bearer token formats**

HMAC-derived (time-limited):

```
Authorization: Bearer opsswarm:read <40-char-hex>
```

Where `<hex>` = HMAC-SHA256 of `<method>:<path>:<unix_timestamp>` using the
`OPSWARM_RUNTIME_SECRET` env var. Valid for 5 minutes; timestamp must be within
±60 s of server clock.

Static pre-shared key (rotation requires env reload):

```
Authorization: Bearer <OPSWARM_API_KEY_<SCOPE>>
```

**Production fail-closed behaviour**

At FastAPI startup, if `APP_ENV=production` and neither `OPSWARM_RUNTIME_SECRET`
nor any `OPSWARM_API_KEY_<SCOPE>` is set, the application raises `RuntimeError`
and refuses to bind its port. Missing auth config does not result in silent
unauthenticated access.

**`/metrics` endpoint**

`GET /metrics` requires `opsswarm:admin`. Expose only behind a network policy,
reverse proxy, or IP allowlist in production. The endpoint exposes internal
operational state; treat it as sensitive infrastructure.

**GitHub webhook independence**

`POST /webhooks/github` is not subject to `opsswarm:*` scopes. It validates the
GitHub HMAC-SHA256 signature using `GITHUB_WEBHOOK_SECRET` and then evaluates
human authority via GitHub collaborator permission. This is a separate trust
domain from Runtime API bearer tokens.

### Error sanitation (Issue #29)

Every exception at the API or orchestrator layer is assigned a 12-character hex
correlation ID. The ID appears in operator logs (ERROR level, with redacted detail)
and in GitHub comments (at the end, preceded by "Ref: ").

GitHub comments contain only:
- A fixed failure banner ("OpsSwarm — Failed / Recovery failed / Verification failed")
- A sanitised error category (never the raw exception text, stderr, or stack trace)
- The correlation ID

Redacted patterns include GitHub PATs (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`),
Bearer/Authorization header values, AWS keys and secrets, `secret=`/`token=`/
`password=` in JSON, and generic API key patterns. The full pattern list is in
`opsswarm/errors.py`. `sanitize_for_log()` additionally preserves file paths for
operator use.

Implementation:
- `api.py` webhook handler: `PermissionError` and generic `Exception` caught; raw
  message never posted.
- `orchestrator.py` failure paths: `run.error` and `run.execution.summary` passed
  through `sanitize_for_comment()` before embedding in a comment.
- `openclaw.py` `run_text()`: non-zero exit raises `OpenClawErrorSanitized` with
  sanitised stderr; raw stderr logged at ERROR level with tokens redacted.

Production fail-closed: if `APP_ENV=production` and auth config is missing, the
service returns `503` for protected endpoints rather than allowing unauthenticated
access.

## Application security model

- GitHub webhook bodies are validated with HMAC-SHA256.
- Human authority is derived from GitHub repository collaborator permission.
- READ and SAFE_WRITE may run automatically according to policy.
- RISKY_WRITE requires explicit approval by a sufficiently privileged GitHub user.
- DESTRUCTIVE is denied by default even if a user attempts approval.
- Free-text comments never authorize side effects.
- OpenClaw specialist prompts constrain investigation profiles to read-only work.
- Ambiguous writes are never blindly retried.
- S7 verification is independent of recovery execution.

For production, enable OpenClaw sandbox and tool allowlists appropriate to each profile. Restrict the recovery
responder's credentials to the minimum required scope.

## Reporting a vulnerability

Use GitHub private vulnerability reporting when it is enabled for the repository. Otherwise, contact the maintainers
through a private channel. Do not disclose a suspected vulnerability in a public issue, discussion, pull request, commit
message, or CI log.

Coordinated disclosure is preferred. The response targets are acknowledgment within 24 hours for critical reports and
within 7 days for high-severity reports; these are operational targets, not guarantees. Public disclosure should wait
until a fix is available or a mutually agreed disclosure deadline is reached.

## Supported versions

| Version | Python | Support status      |
|---------|--------|---------------------|
| 2.1.x   | >=3.11 | Current stable line |
| <2.1    | Any    | Unsupported         |

Unsupported versions may not receive security fixes. Upgrade to the current stable line before reporting behavior that
has already been corrected there.

## Security CI controls

The [`Security CI` workflow](../.github/workflows/security.yml) defines the following policy:

| Trigger          | Controls                                                                                                   |
|------------------|------------------------------------------------------------------------------------------------------------|
| Pull request     | Bandit HIGH-severity/HIGH-confidence gate, pip-audit, Gitleaks, license inventory, and CycloneDX JSON SBOM |
| Push to `master` | Full security suite, including CodeQL Python `security-extended` analysis                                  |
| Weekly schedule  | Full security suite and full-history secret scan                                                           |
| Manual dispatch  | Full security suite                                                                                        |

CodeQL publishes security analysis using its job-scoped `security-events: write` permission. Other jobs use read-only
repository contents. Gitleaks blocks confirmed secret findings. Pip-audit findings fail closed unless an approved, exact
waiver exists. The license step generates an inventory and does not apply an unapproved blanket allowlist.

This document describes the repository policy and workflow configuration. It does not assert that any GitHub-hosted
workflow run has completed successfully.

## Artifact policy

Security CI generates these files under the gitignored `artifacts/` directory:

- `bandit.json`
- `pip-audit.json`
- `licenses.json`
- `sbom.cdx.json`

The shared `scripts/validate-artifacts.py` validator must accept every file before upload. It rejects malformed or
nonconforming input and obvious credential patterns without printing matched values. This validation reduces accidental
disclosure risk; it cannot establish that every possible secret is absent.

Validated security evidence is retained for 30 days. Raw Gitleaks reports are never uploaded because a report could
reproduce a discovered credential. Release evidence uses the same validator before artifact upload or draft-release
creation and uses the same CycloneDX JSON SBOM contract.

See [ADR-010](./adr/ADR-010_SECURITY_WORKFLOW_AND_POLICY.md) for the governing security workflow and artifact decisions.

## Secrets policy

- Never place secrets in issues, comments, pull requests, commit messages, logs, test fixtures, documentation, or CI
  artifacts.
- Store production credentials only in an approved secret store and grant the minimum scope required.
- Treat a confirmed secret as an incident: block the change, revoke or rotate the credential immediately, and review
  relevant access logs.
- A Gitleaks false-positive allowance must be narrowly scoped to a rule or commit, linked to a tracker, approved by the
  security owner, and include an expiry date.
- Do not upload a secret-bearing report as evidence, even after a credential has been revoked.

## Findings and waivers

High or critical dependency findings block merge. An exception must include all of the following:

- Exact CVE or advisory identifier.
- Exact package name and affected version.
- Risk assessment and compensating controls.
- Expiry no later than 90 days after approval.
- Security-owner approval.
- A linked tracking issue or accepted ADR.

No global pip-audit ignore is permitted. Medium and low findings must be tracked explicitly; any tool-level ignore
remains scoped to the exact advisory and package version.

Bandit HIGH/HIGH findings block merge. A suppression requires `# nosec <ID>`, a nearby rationale, and a linked tracker
issue. CodeQL dismissals require the alert reason, accountable owner, linked issue, and expiry or review date in
GitHub's security alert record.

License inventory is evidence for review, not an implicit approval. Unknown, unclassified, or potentially incompatible
licenses require release-owner or legal adjudication before a release policy can allow them.
