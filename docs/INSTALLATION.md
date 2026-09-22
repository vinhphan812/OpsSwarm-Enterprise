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

Create a fine-grained token for the target repository with permissions sufficient to read/write Issues and read collaborator permission. Set:

```bash
export GITHUB_TOKEN=...
export GITHUB_REPO=owner/repo
export GITHUB_WEBHOOK_SECRET=...
```

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
