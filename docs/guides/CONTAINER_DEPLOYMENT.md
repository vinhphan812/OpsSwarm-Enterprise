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

## Kubernetes

### Manifest (core objects only; see the separate K8s task for full manifests)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opsswarm-env
data:
  PORT: "8080"
  # OPSWARM_OPENCLAW_BIN is set in the Secret below

---
apiVersion: v1
kind: Secret
metadata:
  name: opsswarm-secrets
type: Opaque
stringData:
  OPSWARM_OPENCLAW_BIN: /opt/openclaw/openclaw   # path inside the init/sidecar container
  GITHUB_TOKEN: ghp_...                          # GitHub PAT with repo scope

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: opsswarm
  labels:
    app: opsswarm
spec:
  replicas: 1
  selector:
    matchLabels:
      app: opsswarm
  template:
    metadata:
      labels:
        app: opsswarm
    spec:
      # Security: run as non-root (matches Dockerfile USER directive)
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
      containers:
        - name: opsswarm
          image: your-registry/opsswarm:v2.2.0
          ports:
            - containerPort: 8080
          envFrom:
            - configMapRef:
                name: opsswarm-env
          env:
            - name: OPSWARM_OPENCLAW_BIN
              valueFrom:
                secretKeyRef:
                  name: opsswarm-secrets
                  key: OPSWARM_OPENCLAW_BIN
            - name: GITHUB_TOKEN
              valueFrom:
                secretKeyRef:
                  name: opsswarm-secrets
                  key: GITHUB_TOKEN
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: opsswarm-data
              mountPath: /var/lib/opsswarm
            - name: openclaw-bin
              mountPath: /opt/openclaw
              readOnly: true
          # Readiness probe: HTTP GET /health
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          # Liveness probe: keep the pod alive
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 30
            timeoutSeconds: 5
            failureThreshold: 3
          # Graceful termination: allow 60 s for in-flight requests
          terminationGracePeriodSeconds: 60
      volumes:
        - name: opsswarm-data
          persistentVolumeClaim:
            claimName: opsswarm-data-pvc
        - name: openclaw-bin
          # Populate this volume with the OpenClaw binary (init container,
          # sidecar, or pre-populated volume)
          emptyDir: {}
```

### OpenClaw sidecar pattern

If OpenClaw must run in the same pod as OpsSwarm but with different resource limits,
use an init container to extract the binary and a sidecar to run it:

```yaml
initContainers:
  - name: openclaw-init
    image: your-openclaw-image:v1.x.x
    command: ["cp", "/openclaw", "/opt/openclaw/openclaw"]
    volumeMounts:
      - name: openclaw-bin
        mountPath: /opt/openclaw
```

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
