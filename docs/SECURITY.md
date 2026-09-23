# Security model

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
