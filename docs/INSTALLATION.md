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

## 5. Canonical Container and Kubernetes Profile (Issue #73)

This documentation change does **not** introduce a second manifest tree. The
canonical container-delivery implementation is the
[`feature/pr93-remediation` branch / PR #104](https://github.com/vinhphan812/OpsSwarm-Enterprise/pull/104):

- [`Dockerfile`](https://github.com/vinhphan812/OpsSwarm-Enterprise/blob/feature/pr93-remediation/Dockerfile)
  and [`requirements.lock`](https://github.com/vinhphan812/OpsSwarm-Enterprise/blob/feature/pr93-remediation/requirements.lock)
  define the image build inputs.
- [`k8s/base/deployment.yaml`](https://github.com/vinhphan812/OpsSwarm-Enterprise/blob/feature/pr93-remediation/k8s/base/deployment.yaml),
  [`pvc.yaml`](https://github.com/vinhphan812/OpsSwarm-Enterprise/blob/feature/pr93-remediation/k8s/base/pvc.yaml),
  and [`secret.yaml`](https://github.com/vinhphan812/OpsSwarm-Enterprise/blob/feature/pr93-remediation/k8s/base/secret.yaml)
  define the Kubernetes profile.
- [`docs/guides/CONTAINER_DEPLOYMENT.md`](https://github.com/vinhphan812/OpsSwarm-Enterprise/blob/feature/pr93-remediation/docs/guides/CONTAINER_DEPLOYMENT.md)
  is the operator runbook; follow it rather than copying a manifest from this page.

### Deployment boundaries

- The Deployment is deliberately `replicas: 1` with `strategy: Recreate`.
  Scaling beyond one replica requires the distributed-state work tracked by Issue
  #70.
- Persistent state is supplied through the canonical PVCs: evidence at
  `/var/lib/opsswarm` and runtime state at `/app/runtime-data`. Do not run more
  than one writer against those stores.
- The workload runs as UID/GID `10001`, disallows privilege escalation, drops all
  Linux capabilities, and uses the runtime-default seccomp profile. The current
  canonical manifest sets `readOnlyRootFilesystem: false` because the application
  persists state in its writable mounts; do not represent a read-only-root profile
  as the default Kubernetes configuration.
- `GET /health` is the liveness endpoint. `GET /ready` is the dependency and
  lifecycle gate used by the Kubernetes readiness probe; it returns `503` while
  startup, draining, or failure checks are incomplete.
- Create production credentials out of band using an approved secret manager,
  External Secrets, or Sealed Secrets. The repository's Secret manifest is a
  placeholder template and must never be populated with real values in Git.

### Supply-chain evidence

[`container-delivery.yml`](https://github.com/vinhphan812/OpsSwarm-Enterprise/blob/feature/pr93-remediation/.github/workflows/container-delivery.yml)
configures SBOM/provenance generation, fail-closed Trivy scanning, immutable
registry-digest capture, and a pull-by-digest check. Workflow configuration and
CI success are not release or deployment acceptance evidence. For a specific
image, retain the successful workflow artifacts, the exact `sha256` manifest
digest, and the result of any applicable provenance/attestation verification;
do not describe an image as signed or attested unless that verification actually
succeeds.
