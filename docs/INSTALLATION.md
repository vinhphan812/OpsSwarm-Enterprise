# Installation

## 1. Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

## 2. OpenClaw

Install OpenClaw separately and authenticate/configure your chosen model provider. Initialize a Gateway installation:

```bash
openclaw setup --baseline
```

Edit `openclaw/openclaw.patch.json5` and replace `REPLACE_WITH_ABSOLUTE_REPO_PATH`.

```bash
openclaw config patch --file openclaw/openclaw.patch.json5 --dry-run
openclaw config patch --file openclaw/openclaw.patch.json5
openclaw config validate
openclaw gateway start
openclaw agents list
```

Check a profile manually:

```bash
openclaw agent --agent opsswarm-observability-investigator --message "Return only: OK" --json
```

## 3. GitHub

Create a fine-grained token for the target repository with permissions sufficient to read/write Issues and read
collaborator permission. Set:

```bash
export GITHUB_TOKEN=...
export GITHUB_REPO=owner/repo
export GITHUB_WEBHOOK_SECRET=...
```

### GitHub Enterprise Server (GHES)

OpsSwarm supports GHES without source-code edits. Configure the approved API origin and optional CA bundle:

```bash
# Single GHES instance
export OPSWARM_GITHUB_ORIGINS=https://ghes.example.com

# Multi-tenant: GHES + GitHub.com fallback
export OPSWARM_GITHUB_ORIGINS=https://ghes.example.com,https://api.github.com

# Enterprise PKI: point to your corporate CA bundle
export OPSWARM_GITHUB_CA_BUNDLE=/etc/ssl/certs/enterprise-ca-bundle.pem
```

Equivalently, add to `config/production.yaml`:

```yaml
github:
  origins:
    - https://ghes.example.com
    # - https://api.github.com   # uncomment to allow GitHub.com as fallback
  ca_bundle: /etc/ssl/certs/enterprise-ca-bundle.pem
```

**Security notes:**
- `OPSWARM_GITHUB_ORIGINS` accepts only HTTPS origins in production (HTTP is only permitted in `test`/`dev` profiles via `OPSWARM_PROFILE=dev`).
- Origins are validated with exact URL matching — no substring or prefix tricks can bypass the allowlist.
- The AWS/GCP metadata IP (`169.254.169.254`) and `localhost` are always blocked.
- `verify=False` is prohibited in production; use `ca_bundle` instead for self-signed certificates.

Add a repository webhook:

- Payload URL: `https://HOST/webhooks/github`
- Content type: `application/json`
- Secret: same as `GITHUB_WEBHOOK_SECRET`
- Events: Issues, Issue comments

## 4. OpsSwarm service

```bash
export OPSWARM_CONFIG=config/production.yaml
uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088
```

`GET /health` should return `ok: true`.

## 5. Container & Kubernetes Deployment (Issue #73)

### OCI Container Image
OpsSwarm can be deployed as an immutable OCI container image built with hash-locked dependencies (`requirements.lock`) and a pinned Python 3.11 base image digest.

- **Non-root Execution:** Runs as a non-root user/group (UID/GID `10001`).
- **Read-Only Root Filesystem:** Runs with `readOnlyRootFilesystem: true`.
- **Durable State:** Requires a single-writer persistent volume mounted at `/var/lib/opsswarm` (`OPSWARM_DATA_DIR`).

### Kubernetes Deployment Profile
The production Kubernetes deployment profile enforces the single-replica safety contract and container hardening standards:

- **Single Replica & Recreate Strategy:** `replicas: 1` and `strategy: Recreate` (multi-replica scaling requires Issue #70 distributed state coordination).
- **Security Context:** `runAsNonRoot: true`, `runAsUser: 10001`, `runAsGroup: 10001`, `allowPrivilegeEscalation: false`, dropped Linux capabilities (`cap_drop: [ALL]`), and runtime-default seccomp profile.
- **Storage:** PersistentVolumeClaim (PVC) with single-writer access mode mounted at `/var/lib/opsswarm`.
- **Probes:** `startupProbe` and `livenessProbe` configured against `GET /health`.
- **Secrets & Config:** ConfigMaps for non-secret settings; Kubernetes Secrets or external secret store integration for `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, and `OPSWARM_RUNTIME_SECRET`.

### Supply-Chain Verification
Released images are verified via:
1. **SBOM Generation:** CycloneDX/SPDX SBOM generated from the built container image.
2. **Vulnerability Scanning:** Fail-closed Trivy scans checking for HIGH/CRITICAL vulnerabilities.
3. **Digest Pinning & Attestation:** Signed image digests with GitHub OIDC build provenance attestation (`gh attestation verify`).
