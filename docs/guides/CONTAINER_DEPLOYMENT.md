# Container Deployment Guide

This guide covers deploying OpsSwarm Enterprise as an OCI container. It assumes you
are familiar with Docker or a Kubernetes cluster.

---

## Image

| Property    | Value                                          |
|-------------|------------------------------------------------|
| Registry    | ghcr.io (release builds); build locally for dev |
| Tag         | `v{version}` e.g. `v2.2.0`                     |
| Architecture | linux/amd64, linux/arm64                       |

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

| Variable                   | Required | Default   | Description                                   |
|----------------------------|----------|-----------|-----------------------------------------------|
| `PORT`                     | No       | `8080`    | Port uvicorn binds                            |
| `OPSWARM_OPENCLAW_BIN`     | Yes      | —         | Absolute path to the OpenClaw binary          |
| `GITHUB_TOKEN`             | Yes      | —         | GitHub PAT with repo and issue scopes         |
| `OPSWARM_EVIDENCE_BACKEND` | No       | `file`    | Evidence store backend (`file`, `memory`)     |

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
