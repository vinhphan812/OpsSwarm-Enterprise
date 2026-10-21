# Container Deployment Guide

This guide covers deploying OpsSwarm Enterprise as an OCI container. It assumes you
are familiar with Docker or a Kubernetes cluster.

---

## Image

| Property     | Value                                                    |
|--------------|----------------------------------------------------------|
| Registry     | ghcr.io (release builds); build locally for dev          |
| Tag          | `v{version}` e.g. `v2.2.0`                              |
| Architecture | linux/amd64, linux/arm64                                |

The image is produced by the `release.yml` CI workflow and is not published to a
public registry by default. For internal use, push the image tag to your registry:

```bash
docker tag opsswarm-release:v2.2.0 your-registry/opsswarm:v2.2.0
docker push your-registry/opsswarm:v2.2.0
```

---

## Prerequisites

### OpenClaw binary

OpsSwarm requires the OpenClaw AI reasoning runtime. It is not bundled in the image
layers — you supply it at runtime via the `OPSWARM_OPENCLAW_BIN` environment variable.

Obtain the OpenClaw binary from your OpenClaw distribution (e.g. extracted tarball,
installed via a package manager, or downloaded from the OpenClaw releases page).
Place it on the host or in a Kubernetes volume, then pass its absolute path.

### Evidence store directory

The `/var/lib/opsswarm` directory inside the container must be writable. Bind it to
a host directory or a Kubernetes PersistentVolumeClaim:

```bash
mkdir -p /data/opsswarm
chmod 700 /data/opsswarm
```

---

## Docker

### Build (optional — use the published image in production)

```bash
docker build -f Dockerfile -t opsswarm:local .
```

### Run

```bash
# Minimal run (non-root verified)
docker run --rm -u 10001:10001 \
  -p 8080:8080 \
  -e OPSWARM_OPENCLAW_BIN=/path/to/openclaw \
  -e GITHUB_TOKEN=ghp_... \
  opsswarm:local
```

### Run with read-only root filesystem

```bash
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw \
  --tmpfs /var/run:rw \
  --tmpfs /var/lib/opsswarm:rw \
  -p 8080:8080 \
  -e OPSWARM_OPENCLAW_BIN=/path/to/openclaw \
  -e GITHUB_TOKEN=ghp_... \
  opsswarm:local
```

### Verify non-root

```bash
docker run --rm -it --entrypoint id opsswarm:local
# Expected output: uid=10001(appuser) gid=10001(appgroup) groups=10001(appgroup)
```

### Verify health endpoint

```bash
docker run --rm -d -p 8080:8080 \
  -e OPSWARM_OPENCLAW_BIN=/path/to/openclaw \
  -e GITHUB_TOKEN=ghp_... \
  opsswarm:local

sleep 5
curl http://localhost:8080/health
# Expected: {"ok":true,"version":"2.2.0","architecture":"openclaw+github"}
```

---

## Docker Compose — local / single-node deployment

### Quick start

```bash
# 1. Create .env from the example
cp .env.example .env

# 2. Edit .env — at minimum set:
#    OPSWARM_OPENCLAW_BIN=/path/to/openclaw
#    GITHUB_TOKEN_FILE_HOST=$(pwd)/.github-token

# 3. Create the GitHub token file (0600 permissions required)
echo -n "ghp_your_token_here" > .github-token
chmod 0600 .github-token

# 4. Start OpsSwarm
docker compose up -d

# 5. Verify health
curl http://localhost:8080/health
```

### docker compose up — reference

```bash
# Production profile (default)
docker compose up -d

# Include the optional OpenClaw sidecar service
docker compose --profile openclaw up -d

# Rebuild after source changes
docker compose build opsswarm && docker compose up -d

# View logs
docker compose logs -f opsswarm

# Stop
docker compose down

# Stop and destroy persistent volumes (resets state)
docker compose down -v
```

### docker compose config

Validate the compose file renders without errors:

```bash
docker compose config
```

Expected output: the fully merged compose configuration (override applied on top of
the base `docker-compose.yml`).

---

## Secret injection pattern

OpsSwarm **never** reads secrets from image layers.  The GitHub PAT must be supplied
at runtime.  Three options are supported, in order of preference:

### Option 1 — Token file mounted from the host (default, recommended)

```bash
# Create the token file
echo -n "ghp_your_personal_access_token" > .github-token
chmod 0600 .github-token

# Set the host path in .env
echo "GITHUB_TOKEN_FILE_HOST=$(pwd)/.github-token" >> .env
```

`docker-compose.yml` mounts this file as read-only at `/run/secrets/github-token`
inside the container.  OpsSwarm reads `GITHUB_TOKEN_FILE` from the environment
(default: `/run/secrets/github-token`) and uses its contents as the GitHub token.

### Option 2 — Docker secret (Docker Swarm / production Compose)

```bash
# Create the secret
echo -n "ghp_your_token" | docker secret create opsswarm-github-token -

# Override the volume mount in a production override file
# docker-compose.prod.yml:
# services:
#   opsswarm:
#     secrets:
#       - source: opsswarm-github-token
#         target: github-token
#         mode: 0400
# secrets:
#   opsswarm-github-token:
#     external: true
```

### Option 3 — Plain env var (dev only; not recommended)

```bash
# In .env — the token is visible in the environment; avoid in production
echo "GITHUB_TOKEN=ghp_your_token" >> .env
```

Set `GITHUB_TOKEN_FILE` to empty in `.env` to fall back to `GITHUB_TOKEN`.

---

## Persistent state contract

OpsSwarm persists state in two named Docker volumes:

| Volume name                   | Container mount point       | Contents                                         |
|-------------------------------|-----------------------------|--------------------------------------------------|
| `opsswarm-runtime-data`       | `/app/runtime-data`        | Run metadata, checkpoint files, orchestrator state |
| `opsswarm-evidence-store`     | `/var/lib/opsswarm`         | Evidence artefacts (JSON, attachments)            |

**Restart behaviour:** both volumes survive `docker compose stop` and `docker compose down`.
Only `docker compose down -v` destroys them.

**Volume lifecycle:**

```bash
# Inspect volume contents (from the host)
docker run --rm -v opsswarm-runtime-data:/data:ro \
  alpine ls /data/runs

# Reset all persistent state (destroys run history and evidence)
docker compose down -v
docker compose up -d
```

**Evidence store `/var/lib/opsswarm`:** do not bind-mount a host directory as
`/var/lib/opsswarm` on a read-only root filesystem unless the host path is owned
by uid 10001 (appuser) or has world-readable permissions.  The named volume
(`opsswarm-evidence-store`) handles ownership automatically.

---

## Prometheus integration

OpsSwarm exposes a Prometheus-compatible `/metrics` endpoint at port 8080.

| Endpoint    | Auth required | Description                                 |
|-------------|---------------|---------------------------------------------|
| `/health`   | No            | Liveness/readiness probe                    |
| `/metrics`  | Yes (`admin` scope) | Prometheus metrics in text format    |

### Scrape with basic-auth

Generate a bearer token for the monitoring user and pass it as HTTP Basic Auth:

```bash
# Generate a monitoring token (see docs/guides/METRICS_INTEGRATION.md for setup)
MONITORING_TOKEN="your-opsswarm-admin-token"

# Verify /metrics is reachable with the token
curl -H "Authorization: Bearer $MONITORING_TOKEN" http://localhost:8080/metrics
```

### Prometheus scrape config

Add a `scrape_config` entry to your `prometheus.yml`:

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: opsswarm
    static_configs:
      - targets:
          - "opsswarm:8080"       # service name inside the compose network
          # Or the host address when Prometheus runs outside Compose:
          # - "host.docker.internal:8080"
    metrics_path: /metrics
    basic_auth:
      # OpsSwarm reads the Authorization header as a bearer token and validates
      # it against the configured monitoring token (OPSWARM_MONITORING_TOKEN).
      # Use the same token configured in OpsSwarm's auth setup.
      username: opsswarm
      password: "your-opsswarm-admin-token"
    scrape_interval: 30s
    scrape_timeout: 10s
```

When Prometheus runs **outside** the Compose network, use `host.docker.internal`
(the host machine's IP) instead of the service name:

```yaml
    static_configs:
      - targets:
          - "host.docker.internal:8080"
```

On Linux, add `--add-host=host.docker.internal:host-gateway` to the Prometheus
`docker run` command so `host.docker.internal` resolves correctly.

### Prometheus scrape with token auth (no basic-auth)

If your monitoring setup uses a bearer token instead of basic-auth:

```bash
# One-shot scrape with curl (verify the endpoint works)
curl -H "Authorization: Bearer $MONITORING_TOKEN" http://localhost:8080/metrics
```

```yaml
# prometheus.yml — bearer token auth
scrape_configs:
  - job_name: opsswarm
    static_configs:
      - targets: ["host.docker.internal:8080"]
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials: "your-opsswarm-admin-token"
```

### Alerting rules (example)

```yaml
# opsswarm-alerts.yml — Prometheus alerting rules
groups:
  - name: opsswarm
    interval: 30s
    rules:
      - alert: OpsSwarmDown
        expr: up{job="opsswarm"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "OpsSwarm is down"

      - alert: OpsSwarmHighActiveRuns
        expr: opsswarm_active_runs_total > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "OpsSwarm has {{ $value }} active runs"
```

---

## Kubernetes / Kustomize

The repository ships a deployable Kustomize layout, rather than requiring operators
to copy the illustrative manifest above:

- `k8s/base/` contains the namespace, ConfigMap, Deployment, Service, PDB, and
  NetworkPolicy.
- `k8s/overlays/dev/` and `k8s/overlays/prod/` apply environment-specific patches.
- `k8s/base/secret.yaml` is a template with placeholders. Do not apply it with
  real credentials committed to the repository.

### Prerequisites

Install `kubectl` with Kustomize support and select the target cluster context:

```bash
kubectl version --client
kubectl config current-context
```

Create the runtime Secret out-of-band before applying an overlay. For a development
cluster, create it from literals without recording them in shell history or source
control:

```bash
kubectl create namespace opsswarm --dry-run=client -o yaml | kubectl apply -f -
kubectl -n opsswarm create secret generic opsswarm-secrets \
  --from-literal=GITHUB_TOKEN_FILE=/run/secrets/github-token \
  --from-literal=OPSWARM_OPENCLAW_BIN=/opt/openclaw/openclaw \
  --dry-run=client -o yaml | kubectl apply -f -
```

For production, use an approved secret manager, External Secrets, or Sealed Secrets
rather than literal values. The GitHub token itself belongs in the secret manager;
never put it in `k8s/` files or Kustomize patches.

### Render, validate, and deploy

Render first and inspect the exact resources that Kustomize will apply:

```bash
kubectl kustomize k8s/overlays/dev > /tmp/opsswarm-dev.yaml
kubectl apply --dry-run=server -k k8s/overlays/dev
```

Apply the development overlay, wait for the rollout, and verify the health endpoint:

```bash
kubectl apply -k k8s/overlays/dev
kubectl rollout status deployment/opsswarm -n opsswarm --timeout=120s
kubectl get pods,service,pdb,networkpolicy -n opsswarm
kubectl port-forward -n opsswarm service/opsswarm 8080:8080
# In another terminal: curl http://127.0.0.1:8080/health
```

For production, pin the image tag or digest in `k8s/overlays/prod/kustomization.yaml`
before deployment, then use the same render and rollout gates:

```bash
kubectl kustomize k8s/overlays/prod > /tmp/opsswarm-prod.yaml
kubectl apply --dry-run=server -k k8s/overlays/prod
kubectl apply -k k8s/overlays/prod
kubectl rollout status deployment/opsswarm -n opsswarm --timeout=120s
```

If the readiness or health verification fails, stop promotion and roll back only after
reviewing logs and events:

```bash
kubectl describe deployment/opsswarm -n opsswarm
kubectl logs deployment/opsswarm -n opsswarm --all-containers --tail=200
kubectl rollout undo deployment/opsswarm -n opsswarm
kubectl rollout status deployment/opsswarm -n opsswarm --timeout=120s
```

### OpenClaw sidecar and persistent storage

The base Deployment expects the OpenClaw binary at the value supplied by
`OPSWARM_OPENCLAW_BIN`. Supply it through an approved sidecar, init container, or
read-only mounted volume; do not embed it in the OpsSwarm image. Persistent evidence
uses `/var/lib/opsswarm`; provision storage appropriate to the cluster before raising
replica counts. Review the NetworkPolicy with the cluster networking team to confirm
that DNS, GitHub API, OpenClaw, and Prometheus traffic are permitted for the chosen
CNI.

---

## Environment variables

| Variable                   | Required | Default                        | Description                                   |
|----------------------------|----------|--------------------------------|-----------------------------------------------|
| `PORT`                     | No       | `8080`                         | Port uvicorn binds                            |
| `OPSWARM_OPENCLAW_BIN`     | Yes      | —                              | Absolute path to the OpenClaw binary          |
| `GITHUB_TOKEN`             | Yes*     | —                              | GitHub PAT with repo and issue scopes         |
| `GITHUB_TOKEN_FILE`        | No       | `/run/secrets/github-token`    | Path to mounted token file (preferred over env) |
| `OPSWARM_CONFIG`           | No       | `config/production.yaml`       | Config file path inside the container         |
| `OPSWARM_DATA_DIR`         | No       | `runtime-data`                 | Directory for run metadata and checkpoints     |
| `OPSWARM_EVIDENCE_BACKEND` | No       | `file`                         | Evidence store backend (`file`, `memory`)     |

\* Either `GITHUB_TOKEN_FILE` (recommended) or `GITHUB_TOKEN` must be set.

---

## Supply-chain evidence

After a release, the following artifacts are available as workflow artifacts on the
[Releases page](https://github.com/{owner}/{repo}/releases) and in the CI run summary:

- **`sbom.spdx.json`** — SPDX-formatted Software Bill of Materials for the container
  image (90-day retention).
- **`trivy.sarif`** — Trivy vulnerability scan results in SARIF format. Fails the
  release CI job if any CRITICAL or HIGH severity finding is present (fail-closed).
- **`IMAGE_DIGEST.txt`** — Content-addressable image digest (e.g.
  `sha256:a3f5...c9d`). Use this for deterministic image references:
  `docker pull ghcr.io/{owner}/{repo}@sha256:a3f5...c9d`

For local verification of the Trivy report:

```bash
# Download trivy SARIF from the workflow artifact, then:
trivy sarif artifacts/release/trivy.sarif
```

For local SBOM inspection:

```bash
# Install syft
syft packages docker:your-registry/opsswarm:v2.2.0 -o spdx-json
```
