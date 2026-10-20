# Container Deployment Guide

> Scope: Docker and Kubernetes deployment of OpsSwarm Enterprise v2.2.0.
> This guide covers container image requirements, secret management, Kubernetes manifests,
> upgrade and rollback procedures, and replica scaling guidance.

---

## Table of Contents

1. [Container Image](#1-container-image)
2. [Docker Standalone](#2-docker-standalone)
3. [Kubernetes](#3-kubernetes)
   - [3.1 Prerequisites](#31-prerequisites)
   - [3.2 Secrets](#32-secrets)
   - [3.3 Apply Manifests](#33-apply-manifests)
   - [3.4 Verify Deployment](#34-verify-deployment)
   - [3.5 OpenClaw Binary Setup](#35-openclaw-binary-setup)
4. [Upgrade and Rollback](#4-upgrade-and-rollback)
5. [Replica Scaling Guidance](#5-replica-scaling-guidance)
6. [NetworkPolicy Enforcement](#6-networkpolicy-enforcement)
7. [Trivy Security Scanning](#7-trivy-security-scanning)

---

## 1. Container Image

**Canonical image:** `ghcr.io/vinhphan812/opsswarm-openclaw-github:latest`

Build from source:

```bash
docker build -f Dockerfile -t ghcr.io/vinhphan812/opsswarm-openclaw-github:latest .
docker push ghcr.io/vinhphan812/opsswarm-openclaw-github:latest
```

> **OpenClaw binary:** OpsSwarm does **not** embed the OpenClaw runtime in the image layers.
> The `OPSWARM_OPENCLAW_BIN` environment variable must point to the binary at runtime.
> See [Section 3.5](#35-openclaw-binary-setup) for setup options.

**Image properties:**

| Property | Value |
|---|---|
| Base | `python:3.11-slim` |
| Non-root UID/GID | `10001:10001` (user `appuser`) |
| Exposed port | `8080` |
| Health endpoint | `GET /health` → `{"ok": true, "version": "2.2.0", "architecture": "openclaw+github"}` |
| Entrypoint | `uvicorn opsswarm.api:app` (exec-form, SIGTERM-safe) |

---

## 2. Docker Standalone

```bash
# Build
docker build -f Dockerfile -t opsswarm:latest .

# Run (basic)
docker run --rm -p 8080:8080 \
  -e GITHUB_TOKEN="ghp_xxx" \
  -e OPSWARM_OPENCLAW_KEY="sk-xxx" \
  -e OPSWARM_OPENCLAW_BIN="/path/to/openclaw" \
  -e OPSWARM_CONFIG="/app/config/production.yaml" \
  -e APP_ENV="production" \
  -v /path/to/openclaw:/usr/local/bin/openclaw:ro \
  -v opsswarm-data:/var/lib/opsswarm \
  --read-only \
  --tmpfs /tmp:rw \
  --tmpfs /var/run:rw \
  opsswarm:latest
```

Flags explained:

| Flag | Purpose |
|---|---|
| `--read-only` | Root filesystem is read-only; explicit write dirs are created in the image |
| `--tmpfs /tmp:rw` | Writable `/tmp` in memory |
| `--tmpfs /var/run:rw` | Writable `/var/run` in memory |
| `-v /path/to/openclaw:/usr/local/bin/openclaw:ro` | Mount OpenClaw binary read-only |
| `-v opsswarm-data:/var/lib/opsswarm` | Persist evidence across restarts |

---

## 3. Kubernetes

### 3.1 Prerequisites

- Kubernetes `1.25+` (for `policy/v1` PDB API)
- A NetworkPolicy-capable CNI (Calico, Cilium, or Weave) for egress controls
- `kubectl` configured with access to the target cluster
- `kustomize` (`kubectl kustomize`) for manifest management
- (GKE only) Workload Identity configured for cloud auth, or a `ServiceAccount` with a mounted key file

### 3.2 Secrets

**⚠️  Never commit credentials to source control.**

OpsSwarm requires two secrets. Choose the approach that matches your environment:

#### Option A — kubectl create (simplest, development)

```bash
kubectl create secret generic opsswarm-secrets \
  --namespace=opsswarm \
  --from-literal=GITHUB_TOKEN='ghp_xxxxxxxxxxxxxxxxxxxx' \
  --from-literal=OPSWARM_OPENCLAW_KEY='sk-xxxxxxxxxxxxxxxxxxxx'
```

#### Option B — sealed-secrets (GitOps-safe)

Install the [Bitnami SealedSecrets](https://github.com/bitnami-labs/sealed-secrets) controller:

```bash
# Encode credentials
$ echo -n 'ghp_xxx' | base64   # → Z2hwX3hoemJhc2U2NGVuY29kZWR0b2tlbg==

# Create SealedSecret manifest
kubeseal --cert <(kubectl get secret -n kube-system sealed-secrets-key -o jsonpath='{.data.tls\.crt}' | base64 -d) \
  --format=yaml <(cat <<EOF
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: opsswarm-secrets
  namespace: opsswarm
spec:
  encryptedData:
    GITHUB_TOKEN: AgA...
    OPSWARM_OPENCLAW_KEY: AgB...
EOF
) > k8s/sealed-secrets.yaml

kubectl apply -f k8s/sealed-secrets.yaml
```

#### Option C — External Secrets Operator (GCP SM / AWS SM / HashiCorp Vault)

Install the [External Secrets Operator](https://external-secrets.io/) and create a matching `ExternalSecret` resource:

```yaml
# k8s/external-secrets.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: opsswarm-secrets
  namespace: opsswarm
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: gcp-secrets-manager
    kind: ClusterSecretStore
  target:
    name: opsswarm-secrets
    creationPolicy: Owner
  data:
    - secretKey: GITHUB_TOKEN
      remoteRef:
        key: opsswarm-github-token
    - secretKey: OPSWARM_OPENCLAW_KEY
      remoteRef:
        key: opsswarm-openclaw-key
```

### 3.3 Apply Manifests

```bash
# ── Development ────────────────────────────────────────────────────────────
# Use the dev overlay.  Replace secret placeholder values in overlays/dev/kustomization.yaml
# OR create the secret manually before applying (recommended).
kubectl create secret generic opsswarm-secrets \
  --namespace=opsswarm \
  --from-literal=GITHUB_TOKEN='REPLACE_WITH_DEV_TOKEN' \
  --from-literal=OPSWARM_OPENCLAW_KEY='REPLACE_WITH_DEV_KEY'

kubectl apply -k k8s/overlays/dev

# ── Production ──────────────────────────────────────────────────────────────
# Ensure the sealed-secret or external-secret is in place before applying.
kubectl apply -k k8s/overlays/prod
```

### 3.4 Verify Deployment

```bash
# Wait for the pod to be ready
kubectl rollout status deployment/opsswarm -n opsswarm --timeout=120s

# Check pod status
kubectl get pods -n opsswarm

# Verify health endpoint (port-forward if not using LoadBalancer)
kubectl port-forward -n opsswarm svc/opsswarm 8080:8080 &
curl http://localhost:8080/health
# Expected: {"ok": true, "version": "2.2.0", "architecture": "openclaw+github"}

# Check logs
kubectl logs -n opsswarm deployment/opsswarm --follow
```

### 3.5 OpenClaw Binary Setup

OpsSwarm loads the OpenClaw binary from the path specified in `OPSWARM_OPENCLAW_BIN`
(default: `/usr/local/bin/openclaw`).  Three production-grade options:

#### Option 1 — Kubernetes init container (recommended for production)

Add an init container to the deployment that downloads the binary at startup:

```yaml
# Add to deployment.yaml spec.template.spec.initContainers:
- name: openclaw-init
  image: curlimages/curl:latest
  command:
    - /bin/sh
    - -c
    - |
      curl -fsSL "${OPENCLAW_URL}" -o /openclaw/openclaw
      chmod +x /openclaw/openclaw
  env:
    - name: OPENCLAW_URL
      valueFrom:
        secretKeyRef:
          name: opsswarm-secrets
          key: OPSWARM_OPENCLAW_URL
  volumeMounts:
    - name: openclaw-bin
      mountPath: /openclaw
```

#### Option 2 — Host path volume (development only)

In `overlays/dev/kustomization.yaml`, the hostPath volume is already patched:

```yaml
# Already configured in overlays/dev — just ensure the node has openclaw at /usr/local/bin/openclaw
# (minikube: minikube ssh "sudo cp $(which openclaw) /usr/local/bin/")
```

#### Option 3 — Sealed secret with base64-encoded binary

```bash
# Encode the binary (do NOT store the encoded string in git)
base64 -i openclaw -o openclaw.b64

# Reference in a sealed secret (see Section 3.2 Option B)
```

---

## 4. Upgrade and Rollback

### Upgrade

```bash
# 1. Build and push the new image
docker build -f Dockerfile -t ghcr.io/vinhphan812/opsswarm-openclaw-github:v2.3.0 .
docker push ghcr.io/vinhphan812/opsswarm-openclaw-github:v2.3.0

# 2. Update the image tag in the prod overlay (or use a git-tag-driven CI pipeline)
#    Edit k8s/overlays/prod/kustomization.yaml:
#    images:
#      - name: ghcr.io/vinhphan812/opsswarm-openclaw-github
#        newTag: "2.3.0"

# 3. Apply the update (RollingUpdate strategy)
kubectl apply -k k8s/overlays/prod

# 4. Monitor the rollout
kubectl rollout status deployment/opsswarm -n opsswarm --timeout=120s
```

### Rollback

```bash
# Roll back to the previous revision
kubectl rollout undo deployment/opsswarm -n opsswarm

# Roll back to a specific revision
kubectl rollout history deployment/opsswarm -n opsswarm
kubectl rollout undo deployment/opsswarm -n opsswarm --to-revision=3
```

### Gated rollout (canary)

For additional safety, use a `kubectl rollout` with `maxSurge: 0, maxUnavailable: 1`
to perform a single-pod canary:

```yaml
# In k8s/base/deployment.yaml — swap to RollingUpdate for multi-replica canaries
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

---

## 5. Replica Scaling Guidance

**Current gate: `replicas: 1` until shared coordination (issue #70) is resolved.**

### Why single-replica is intentional

Without a distributed coordination store, multiple OpsSwarm replicas will each receive the
same GitHub webhook events and create duplicate incidents.  Issue #70 implements shared
state (Redis or Firestore) with distributed locking to enable safe multi-replica scaling.

### When to scale beyond 1 replica

1. Issue #70 is resolved and a coordination store is configured.
2. The `PodDisruptionBudget` in `k8s/base/pdb.yaml` is updated from `minAvailable: 1`
   to `maxUnavailable: 1`.
3. Horizontal scaling and webhook fan-out are tested in a staging environment.

### How to scale

```bash
# After issue #70 is resolved:
kubectl scale deployment opsswarm --namespace=opsswarm --replicas=3

# Or edit k8s/base/deployment.yaml and update replicas: 3
```

---

## 6. NetworkPolicy Enforcement

The `k8s/base/network-policy.yaml` implements a **default-deny ingress / allowlist egress**
model.  Before applying it, verify your CNI supports `NetworkPolicy`:

| CNI | Support |
|---|---|
| Calico | Full |
| Cilium | Full |
| Weave Net | Full |
| Flannel | None (requires Canal / Calico overlay) |
| GKE default | Partial (enable "Network policy" in cluster config) |
| EKS default (VPC-CNI) | None (install Calico via EKS add-on) |
| AKS default | None (install Calico via Azure CLI) |

### Enable the NetworkPolicy

```bash
# Apply only after confirming CNI support
kubectl apply -k k8s/base  # base contains the network-policy.yaml

# Label allowed ingress namespaces
kubectl label namespace <your-ingress-namespace> allow-opsswarm-ingress=true
kubectl label namespace monitoring allow-opsswarm-ingress=true
```

### Allowed egress destinations

| Destination | Port | Purpose |
|---|---|---|
| Kubernetes DNS (kube-dns) | UDP/TCP 53 | Service discovery |
| GitHub API (`140.82.112.0/22`) | TCP 443 | GitHub Issues / PRs |
| OpenClaw runtime (cluster-internal) | TCP 8081 | AI reasoning runtime |
| Cloud metadata service (`169.254.169.254`) | TCP 80 | GCP/AWS workload identity |

### Customise allowed CIDRs

Edit `k8s/base/network-policy.yaml` and update the `ipBlock.cidr` values for your
infrastructure.  For GitHub Enterprise Server, replace the GitHub.com CIDR with
your GHE server's IP range.

---

## 7. Trivy Security Scanning

The container image is scanned at release time (see `.github/workflows/release.yml`).
Trivy runs in **fail-closed** mode: the release pipeline aborts if CRITICAL or HIGH
OS or library vulnerabilities are found.

For ad-hoc scanning in your deployment pipeline:

```bash
# Scan the image
docker run --rm aquasec/trivy image \
  --severity CRITICAL,HIGH \
  --exit-code 1 \
  --ignore-unfixed \
  ghcr.io/vinhphan812/opsswarm-openclaw-github:latest

# Scan at the filesystem level (for CI)
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy fs \
  --severity CRITICAL,HIGH \
  --exit-code 1 \
  .
```

> **Policy:** No CRITICAL or HIGH vulnerabilities in OS packages or application
> dependencies are permitted in production images.  See `docs/SECURITY.md` for the
> full vulnerability threshold policy.

---

## Quick Reference

```bash
# Deploy to dev
kubectl create secret generic opsswarm-secrets --namespace=opsswarm \
  --from-literal=GITHUB_TOKEN='xxx' --from-literal=OPSWARM_OPENCLAW_KEY='xxx'
kubectl apply -k k8s/overlays/dev

# Verify
kubectl rollout status deployment/opsswarm -n opsswarm
curl $(kubectl get svc -n opsswarm opsswarm -o jsonpath='{.status.loadBalancer.ingress[0].ip}'):8080/health

# Upgrade
# 1. Update image tag in overlays/prod/kustomization.yaml
# 2. kubectl apply -k k8s/overlays/prod
# 3. kubectl rollout status deployment/opsswarm -n opsswarm

# Rollback
kubectl rollout undo deployment/opsswarm -n opsswarm
```
