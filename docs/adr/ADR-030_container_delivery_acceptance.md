# ADR-030: Container Delivery Acceptance Contract

**Status:** Proposed
**Created:** 2026-10-21
**Review:** Required before closing Issue #73
**Related:** Issue #73, Issue #70, Issue #30, PR #93

---

## Context

PR #93 (`feat/73-container-delivery`) introduced OCI image, Docker Compose, and
Kubernetes manifests for OpsSwarm Enterprise. Formal review at commit
`e2de536afb56` identified five architectural gaps between the delivered artefacts
and the claims made in the accompanying documentation:

1. **OCI publication** — the release workflow used `load: true` (local daemon) and
   read `.RepoDigests[0]`; a locally loaded image has no registry digest.
2. **OpenClaw trust boundary** — `OPSWARM_OPENCLAW_BIN` was documented as a
   sidecar-supplied path without a defined volume source; the init check and the
   mount path in the manifest had no correspondence.
3. **Readiness semantics** — `/health` was promoted as the readiness probe despite
   not checking GitHub credentials or OpenClaw availability.
4. **K8s base manifest correctness** — `openclaw-bin` had no `volumeSource`;
   `fsGroup` was placed at container level; `emptyDir` discards evidence on pod
   replacement.
5. **Issue #70 gate** — replicas were not explicitly bounded to 1, and no
   documentation prevented HA claims before shared coordination is implemented.

This ADR establishes the authoritative contract that all container-delivery
artefacts must satisfy before production-delivery claims are accepted. It does
**not** modify production code, workflows, Dockerfile, Compose, or K8s manifests.

---

## Decision

### 1. OCI Publication Strategy

#### Supported publication model

An OpsSwarm container release is valid only when the image exists in a **public or
internal OCI registry** and is referenced by its **immutable digest**
(`sha256:…`). Locally built images, images referenced only by mutable tags, and
images present only in the GitHub Actions runner's local Docker daemon are **not**
acceptable evidence of a production deployment.

#### Release workflow requirements

The `release.yml` workflow (or its equivalent) must satisfy all of the following:

| # | Requirement | Rationale |
|---|-------------|-----------|
| P1 | Image is pushed to a named registry (e.g. `ghcr.io/owner/opsswarm`) with a version tag | Immutable registry reference |
| P2 | The push step outputs the full digest line (e.g. `sha256:abc123…`) and it is captured in a workflow output variable | Digest obtained from build/push, not local inspect |
| P3 | The captured digest is verified to start with `sha256:` and to have 64 hex characters before any downstream step uses it | Guard against empty/undefined variable (see `set -u`) |
| P4 | The digest is written to `artifacts/release/IMAGE_DIGEST.txt` and included in the draft release body | Digest available to operators |
| P5 | An image SBOM (SPDX JSON or CycloneDX JSON) is generated from the **registry-pushed** image | SBOM must reflect the exact image that will be pulled |
| P6 | A vulnerability scan (Trivy, Grype, or equivalent) runs against the registry-pushed image at CRITICAL/HIGH with `exit-code 1` (fail-closed) | Confirmed by `--exit-code 1` in `release.yml` step |
| P7 | GitHub OIDC provenance attestation is recorded against the pushed image digest | Verifiable provenance chain |

#### What `load: true` does NOT provide

`docker/build-push-action` with `load: true` builds into the GitHub Actions runner's
local Docker daemon. A locally loaded image has `RepoDigests = []` because it has
never been pushed to a registry. Calling `docker inspect --format='{{.RepoDigests}}'`
on such an image produces an empty string or a fragment with no `sha256:` digest.
The shell variable `full_digest` assigned from this output is therefore empty when
`set -u` is active, causing the workflow to fail or to publish an empty digest
file. The correct approach is to use `push: true` (or `push: false` with a separate
`docker push` step) so the digest is captured from the registry push output.

#### Evidence artefacts

A complete release consists of:

```
artifacts/release/
  opsswarm-{version}-py3-none-any.whl
  opsswarm-{version}.tar.gz
  SHA256SUMS.txt
  sbom.cdx.json           ← CycloneDX wheel SBOM
  sbom.spdx.json          ← SPDX container image SBOM
  IMAGE_DIGEST.txt        ← sha256:… of registry-pushed image
  trivy.sarif             ← Vulnerability scan results
  PROVENANCE.md           ← GitHub OIDC attestation reference
```

---

### 2. OpenClaw Integration Mechanism and Trust Boundary

#### Architectural position

OpenClaw is an **external AI reasoning runtime** that OpsSwarm invokes as a
subprocess or via its gateway API. OpenClaw is **never embedded in the OpsSwarm
container image layers** — this is an explicit non-goal (see ADR-008). The two
components share a host or cluster node via a **shared executable volume** or an
**authenticated local RPC endpoint**. Neither component trusts the other's
filesystem without an explicit mount or credential.

#### Supported runtime boundary modes

OpsSwarm supports exactly **two** integration modes. Operators must choose one;
mixed configurations are not supported.

##### Mode A — Shared executable volume (default)

```
Host/K8s Node
  └── /opt/openclaw/openclaw       ← OpenClaw binary, mode 0755
        ↑
        │  hostPath / PVC / ConfigMap binary
        │
OpsSwarm container
  └── OPSWARM_OPENCLAW_BIN=/opt/openclaw/openclaw
        └── subprocess.execvp("/opt/openclaw/openclaw", …)
```

- The binary must exist on the host before OpsSwarm starts.
- The K8s `openclaw-bin` volume must have a concrete `volumeSource` (hostPath,
  PVC, or downward-API ConfigMap binary). The base manifest must document this
  and overlay configurations must provide it.
- The init container (`openclaw-check`) validates that the path is non-empty,
  that the file exists, and that it is executable (`-x`) before the main
  container proceeds.
- Reconciliation: if the binary is absent at startup, the pod fails to start
  with a clear error message from the init container. OpsSwarm does not retry
  automatically; the operator must mount the binary.
- If `OPSWARM_OPENCLAW_BIN` is set to an empty string, the init container exits
  1 with a descriptive error; the pod does not start.

##### Mode B — Authenticated local RPC endpoint

```
OpsSwarm container
  └── OPSWARM_OPENCLAW_BIN=openclaw
  └── OPENCLAW_GATEWAY_URL=http://localhost:8089
        └── HTTP/REST or stdio-RPC to OpenClaw gateway on the same host/pod
```

- `OPSWARM_OPENCLAW_BIN` is set to the `openclaw` command on PATH.
- `OPENCLAW_GATEWAY_URL` points to the OpenClaw gateway (default:
  `http://localhost:8089`).
- OpsSwarm and the OpenClaw gateway communicate over localhost HTTP.
- Authentication to the gateway uses `OPSWARM_OPENCLAW_KEY` (Bearer token).
- This mode is only suitable when both processes run on the same host or in the
  same Kubernetes pod (shared network namespace).

#### What the sidecar claim does NOT mean

The phrase "sidecar" in OpenClaw documentation refers to **deployment topology**,
not to automatic filesystem sharing. A Kubernetes sidecar container does **not**
automatically make its `/usr/local/bin/openclaw` available to the main container
unless an explicit volume is mounted from the sidecar to the main container.
Claiming sidecar deployment automatically satisfies `OPSWARM_OPENCLAW_BIN` without
a volume mount is incorrect.

#### Reconciliation semantics

| Event | Behaviour |
|-------|-----------|
| Binary absent at startup | Init container fails; pod stuck in `Init:Error`; event message explains missing path |
| Binary removed at runtime | Running subprocess continues; next invocation fails with `FileNotFoundError`; incident not affected |
| OpenClaw gateway unreachable | OpsSwarm returns `dependency_unavailable`; `RunState` transitions to `FAILED`; operator notified |
| Token invalid | OpsSwarm returns `auth_denied`; `RunState` transitions to `FAILED`; operator notified |

---

### 3. Readiness, Liveness, and Draining State Model

#### Three-probe model

OpsSwarm exposes three logical states governed by separate signals:

| Probe | Endpoint | Purpose | Blocks new traffic? | Triggers restart? |
|-------|----------|---------|---------------------|------------------|
| Liveness | `GET /health` | Process alive, uvicorn responsive | No | Yes (after `failureThreshold` failures) |
| Startup | `GET /health` | Application initialised (same signal; acceptable until #30) | Yes (until first success) | No |
| Readiness | **Not `/health`** | Application ready to serve requests with all dependencies satisfied | Yes | No |
| Draining | `GET /health` returns 503 after SIGTERM received | In-flight requests completing | Yes | N/A |

#### `/health` contract

`GET /health` returns `{"ok": true, "version": "<semver>", "architecture": "openclaw+github"}`
with HTTP 200 and no authentication. It verifies only that:

- The FastAPI application has started and uvicorn is listening.
- The Python runtime is responsive.

It does **not** verify:

- That `GITHUB_TOKEN` is valid or has sufficient scope.
- That GitHub API is reachable.
- That OpenClaw is available or correctly configured.
- That evidence/checkpoint persistence is writable.

Therefore `/health` is suitable for **liveness probes** (has the process crashed?)
and for **startup probes** (is the app initialised?), but **not** for readiness.

#### Kubernetes readiness probe

Until Issue #30 is resolved, the readiness probe is a **placeholder**. The
documented behaviour is:

> **Acceptance gate:** `/ready` endpoint or equivalent dependency-check signal
> must exist and return 200 only when GitHub credentials are valid and OpenClaw
> binary is confirmed executable. This is tracked in Issue #30.

Operators must **not** set `readinessProbe` to `/health` and claim production
readiness without the dependency check. The current K8s base manifest documents
this limitation in its header comment.

#### Draining

When the OpsSwarm process receives SIGTERM (or when Kubernetes sends it):

1. OpsSwarm stops accepting new HTTP requests (uvicorn stops routing new work).
2. OpsSwarm allows in-flight GitHub API calls and OpenClaw invocations to complete
   up to `terminationGracePeriodSeconds` (default: 60 s).
3. OpsSwarm performs a final checkpoint save to `/app/runtime-data/runs/`.
4. OpsSwarm exits 0.

`terminationGracePeriodSeconds` must be at least 30 s in all K8s overlays. The
value should cover the worst-case OpenClaw agent invocation duration.

#### GitHub credential readiness

GitHub credential validity is **not** checked by the HTTP surface at startup.
The credential is used on the first outbound call. If that call fails with
`auth_denied`, the `RunState` transitions to `FAILED` and the incident is left
open with a descriptive error. This is the correct behaviour — failing closed
rather than silently proceeding without GitHub access.

---

### 4. K8s Durable-State and Network-Policy Baseline

#### Volume requirements

| Volume | Base manifest | Required source | Rationale |
|--------|---------------|-----------------|-----------|
| `openclaw-bin` | No `volumeSource` in base | **Must be provided by overlay** | Without this the init container fails |
| `evidence-store` (`/var/lib/opsswarm`) | `emptyDir` | **Overlay must replace with PVC** for production | `emptyDir` is lost on pod deletion; evidence is irrecoverable |
| `runtime-data` (`/app/runtime-data`) | `emptyDir` | **Overlay must replace with PVC** for production | Checkpoints are lost on pod deletion |
| `tmp` (`/tmp`) | `emptyDir` | `emptyDir { medium: Memory }` in prod overlay | Prevents tmpfile leakage to host filesystem |

The base manifest must document each volume's purpose and the minimum required
`volumeSource` that an overlay must supply. The base must not be applied to a
cluster without an overlay that provides these sources.

#### `securityContext` placement

`fsGroup` is a **Pod-level** field in `securityContext`. Placing it inside a
container's `securityContext` is rejected by `kubectl apply --dry-run=server` in
Kubernetes 1.27+. The Pod-level `securityContext` is where the following must be
set:

```yaml
spec:
  securityContext:        # ← Pod level
    runAsNonRoot: true
    runAsUser: 10001
    runAsGroup: 10001
    fsGroup: 10001        # ← correct location
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: opsswarm
      securityContext:    # ← Container level (supplements Pod level)
        runAsNonRoot: true
        runAsUser: 10001
        allowPrivilegeEscalation: false
        capabilities:
          drop: [ALL]
```

#### NetworkPolicy baseline

The base `NetworkPolicy` must:

- Allow ingress only from named namespaces (via `namespaceSelector`) and from
  explicitly documented ingress controller CIDRs.
- Allow egress to `api.github.com` (TCP 443) using FQDN-based `to[*].dnsName`
  rather than a fixed CIDR block, because GitHub's IP ranges change without
  notice.
- Allow egress to the OpenClaw runtime host (configurable via
  `OPENCLAW_EGRESS_HOST` in the ConfigMap).
- Allow egress to DNS (UDP+TCP 53) for Kubernetes service discovery.
- Allow egress to cloud metadata services (169.254.169.254, TCP 80/443) only
  when explicitly required by the cloud provider; document this in the overlay.

The base policy must **not** include `ingress[].from[].ipBlock.cidr: 0.0.0.0/0`
as a catch-all. Production overlays must supply the actual ingress controller
CIDRs.

---

### 5. Non-Goals and Issue #70 Gate

#### HA is not supported in v2.2

OpsSwarm Enterprise v2.2 is designed, documented, and delivered as a **single-
instance** service. This is an explicit non-goal, not a current limitation:

> **Non-goal:** Do not claim HA or multi-instance guarantees until shared
> transactional coordination (Issue #70) is complete.

The deployment documentation must include this statement verbatim, and the K8s
base `replicas` field must be set to `1` with a comment linking to Issue #70.

#### What Issue #70 must provide before HA is claimed

| Requirement | Owner |
|-------------|-------|
| Shared transactional run store (PostgreSQL or equivalent) | infra/dev-ops |
| Distributed run ownership / lease mechanism | infra/dev-ops |
| Cross-process deduplication of webhook events and commands | infra/dev-ops |
| Optimistic concurrency / CAS for run record writes | infra/dev-ops |
| Shared rate-limit and anti-replay state | infra/dev-ops |
| Documented HA deployment runbook | docs |
| Multi-process integration tests | test/qa |

Until all of the above are implemented and verified, increasing `replicas` beyond
`1` in the K8s manifests or recommending multi-instance deployment is a policy
violation and must not appear in any OpsSwarm documentation.

---

### 6. Acceptance Tests

The following tests are **required** to be green before Issue #73 may be closed.
Automated tests are in `tests/integration/test_container_deployment.py`.

#### OCI image

| Test | Method | Pass criterion |
|------|--------|----------------|
| Multi-stage build | Inspect Dockerfile | `AS builder` and `AS runtime` stages present; `COPY --from=builder` in runtime |
| Non-root user | `docker run --entrypoint id` | `uid=10001(appuser) gid=10001(appgroup)` |
| No GitHub token in layers | `docker history` | No match for `ghp_`, `ghs_`, `ghu_`, `GHO_`, `GHR_` |
| Healthcheck configured | Inspect Dockerfile | `HEALTHCHECK CMD … /health` present |
| SIGTERM graceful shutdown | `docker stop` | Process exits 0 within `stop_grace_period` |
| SBOM generated | Inspect release workflow | SPDX/CycloneDX JSON artefact uploaded |
| Image digest non-empty | `cat IMAGE_DIGEST.txt` | Starts with `sha256:`; 64 hex characters |
| Vulnerability scan | Inspect `trivy.sarif` | Exit code was 1 on any CRITICAL/HIGH finding |

#### Docker Compose

| Test | Method | Pass criterion |
|------|--------|----------------|
| Config validates | `docker compose config` | Exit code 0 |
| Named volumes declared | Inspect compose file | `opsswarm-runtime-data` in `volumes:` section |
| Token via file mount | Inspect compose file | `GITHUB_TOKEN_FILE`; `/run/secrets/`; `read_only: true` |
| Graceful shutdown | `docker compose stop` | Graceful within 30 s |

#### Kubernetes

| Test | Method | Pass criterion |
|------|--------|----------------|
| Kustomize renders | `kustomize build k8s/` | Exit code 0; `kind:` resources in output |
| Server-side dry-run | `kubectl apply --dry-run=server -k k8s/` | Exit code 0 |
| Non-root securityContext | Inspect `deployment.yaml` | `runAsNonRoot: true`, `runAsUser: 10001` at **Pod** level |
| `fsGroup` at Pod level | Inspect `deployment.yaml` | `fsGroup` under `spec.securityContext`, not under `containers[].securityContext` |
| `openclaw-bin` volume source | Inspect overlay manifest | Concrete `volumeSource` (hostPath / PVC / etc.) present in overlay |
| `evidence-store` PVC | Inspect overlay manifest | `persistentVolumeClaim.claimName` in production overlay |
| `runtime-data` PVC | Inspect overlay manifest | `persistentVolumeClaim.claimName` in production overlay |
| NetworkPolicy egress | Inspect `network-policy.yaml` | `api.github.com` FQDN or resolved CIDR; no `0.0.0.0/0` ingress |
| Replicas = 1 | Inspect `deployment.yaml` | `replicas: 1`; comment references Issue #70 |

---

## Consequences

### Positive

- Production operators receive an unambiguous contract for OCI image provenance,
  OpenClaw integration, and readiness semantics.
- The five blockers identified in the PR #93 review are each assigned to a
  specific owner with an objectively verifiable acceptance test.
- Issue #70 is explicitly gated; HA claims are prohibited until the gate passes.
- K8s base manifest gaps (volume source, `fsGroup` placement, `emptyDir`
  durability) are documented as requiring overlay resolution before production
  use.

### Negative

- Operators must supply an explicit `volumeSource` for `openclaw-bin` in any
  K8s overlay — there is no default that works out of the box.
- The readiness probe cannot claim production-grade dependency checking until
  Issue #30 is resolved; this is now a documented gap.
- Production K8s overlays must replace `emptyDir` with PVC-backed volumes for
  evidence and runtime-data durability; this is an operational requirement, not
  an optional optimisation.

### Neutral

- The ADR is documentation-only. Production code, workflows, Dockerfile, Compose,
  and K8s manifests are modified in follow-on tasks assigned below.
- The ADR does not change any existing approved ADR. It extends the deployment
  layer only.

---

## Follow-on Ownership Matrix

Each blocker is assigned to exactly one owner. No blocker appears in more than
one row.

| # | Blocker description | Owner | Deliverable |
|---|---------------------|-------|-------------|
| R1 | Fix `release.yml`: replace `load: true` with `push: true`; capture digest from push output; verify non-empty `sha256:` before use | **CI/dev-ops** | Updated `.github/workflows/release.yml`; digest artefact in release run |
| R2 | Remove silent fallback in `Dockerfile` `uv pip install` step | **CI/dev-ops** | Updated `Dockerfile` stage 1; build fails on lock resolution error |
| R3 | Add concrete `volumeSource` for `openclaw-bin` in K8s `overlays/dev/` and document `overlays/prod/` requirement | **infra/dev-ops** | Updated `k8s/overlays/dev/kustomization.yaml`; updated `CONTAINER_DEPLOYMENT.md` |
| R4 | Move `fsGroup` from container `securityContext` to Pod-level `securityContext` in `k8s/base/deployment.yaml` | **infra/dev-ops** | Updated `k8s/base/deployment.yaml` |
| R5 | Add PVC-backed volumes for `evidence-store` and `runtime-data` in `k8s/overlays/prod/`; update `CONTAINER_DEPLOYMENT.md` | **infra/dev-ops** | Updated `k8s/overlays/prod/`; updated `CONTAINER_DEPLOYMENT.md` |
| R6 | Replace broad `0.0.0.0/0` ingress in `k8s/base/network-policy.yaml` with FQDN-based egress and documented ingress CIDRs; add `overlays/prod/` policy | **infra/dev-ops** | Updated `k8s/base/network-policy.yaml`; updated `CONTAINER_DEPLOYMENT.md` |
| R7 | Add `/ready` endpoint or dependency-check signal; implement as `readinessProbe` in K8s base (tracked in Issue #30) | **runtime/backend** | Issue #30 closure; updated `deployment.yaml` readiness probe |
| R8 | Confirm `replicas: 1` in K8s base and add Issue #70 non-goal statement to `CONTAINER_DEPLOYMENT.md` and `k8s/base/deployment.yaml` header | **docs** (this ADR) | This ADR; `CONTAINER_DEPLOYMENT.md` updated by R3/R5/R6 |
| R9 | Add `acceptance_test` marker group to `tests/integration/test_container_deployment.py` for R1–R7 regression coverage | **test/qa** | Updated `tests/integration/test_container_deployment.py` |

---

## Alternatives Considered

### OCI publication

| Option | Description | Rejected because |
|--------|-------------|-----------------|
| Use `load: true` + `docker inspect` | Keep local image, read digest from daemon | Local images have no registry digest; empty variable with `set -u` |
| Separate build and push steps | Build locally, then `docker push` | Two steps; digest must be captured from push output correctly |
| Use GitHub OIDC attestation only | Trust provenance without digest | Operators need the digest to pull a specific image version |

### OpenClaw integration

| Option | Description | Rejected because |
|--------|-------------|-----------------|
| Embed OpenClaw in image layers | Copy binary in Dockerfile | Violates ADR-008; forces image rebuild on every OpenClaw update |
| Rely on sidecar filesystem sharing | Assume sidecar makes binary available | No K8s mechanism shares a container's filesystem without explicit volume mount |
| Require authenticated RPC only | No file-based integration | Host-mount volume is simpler for single-node / VM deployments; both modes needed |

### Readiness

| Option | Description | Rejected because |
|--------|-------------|-----------------|
| Use `/health` as readiness | Current implementation | Does not verify GitHub token or OpenClaw availability |
| Readiness probe with shell exec curl | Check GitHub API in probe | Adds latency to every readiness check; credential exposure in probe command |
| Separate readiness service | `/ready` endpoint with dependency checks | Correct solution; tracked in Issue #30 |

---

*End of ADR-030*
