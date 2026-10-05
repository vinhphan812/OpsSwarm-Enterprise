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
