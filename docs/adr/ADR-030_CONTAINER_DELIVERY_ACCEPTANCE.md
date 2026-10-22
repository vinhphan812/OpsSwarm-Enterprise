# ADR-030: Container Delivery Acceptance Contract

**Status:** Accepted

**Created:** 2026-10-21 (Updated & Accepted: 2026-10-22)

**Review:** Verified for Issue #73 closure

**Related:** Issue #73, Issue #70, Issue #30, Issue #99, Issue #102

---

## Context

PR #93 (`feat/73-container-delivery`) introduced OCI image, Docker Compose, and Kubernetes deployment artefacts. Review confirmed that production delivery requires objective delivery evidence and a single canonical lifecycle implementation.

The key architectural decisions and requirements are:

1. **Immutable OCI Registry Digest:** A local Docker image ID or `RepoDigests` from `load: true` is not an OCI registry manifest digest. Production delivery requires a registry-pushed immutable manifest digest (`sha256:` followed by 64 hex characters) and evidence derived from that image.
2. **OpenClaw Integration Boundary:** `OPSWARM_OPENCLAW_BIN` requires an executable-volume boundary. `OpenClawClient` is a subprocess adapter (`asyncio.create_subprocess_exec`), not an HTTP/RPC gateway adapter. Mode A (shared executable volume validated by an init container) is supported; Mode B (`OPENCLAW_GATEWAY_URL` RPC) is an unsupported non-goal for Issue #73.
3. **Canonical Lifecycle & Drain:** `/health` remains liveness-only. Startup readiness, SIGTERM pre-drain, mutable-ingress rejection (`@check_draining`), and background-dispatch tracking are owned by a single process-local owner (`opsswarm/runtime.py` via `ReadinessManager.get_readiness()`), avoiding competing API lifecycle controllers.
4. **Kubernetes Single-Instance Baseline:** K8s deployment requires renderable manifests with `replicas: 1`, concrete volume sources for `openclaw-bin`, PVC-backed state (`OPSWARM_DATA_DIR=/var/lib/opsswarm`), scoped security context (`fsGroup` at pod level), and restricted network policies.
5. **HA Non-Goal:** OpsSwarm remains a single-instance service until Issue #70 supplies shared transactional coordination.

Acceptance is granted following the successful verification and delivery of PR #93 and its associated evidence gates (`t_54e36456`).

---

## Decision

### 1. OCI publication and supply-chain contract

A release is acceptable only when its image has been pushed to a named OCI registry and is identified by the resulting immutable **registry manifest digest** (`sha256:` followed by 64 hexadecimal characters). A mutable tag, local image ID, or image loaded only into the GitHub Actions runner is not equivalent evidence.

The delivery workflow must satisfy:

| ID | Acceptance criterion | Producing evidence type | Status |
|---|---|---|---|
| P1 | Push the OCI image to the registry with a version tag and a pinned SHA tag. | Workflow push log and registry reference. | Satisfied |
| P2 | Capture and validate the registry manifest digest from the push output before it is used. | `artifacts/release/IMAGE_DIGEST.txt`; value matches `^sha256:[0-9a-f]{64}$`. | Satisfied |
| P3 | Generate an SPDX or CycloneDX SBOM from the registry-pushed image. | `artifacts/release/sbom.spdx.json` and/or `sbom.cdx.json`. | Satisfied |
| P4 | Scan the registry-pushed image for CRITICAL/HIGH vulnerabilities and fail closed. | `artifacts/release/trivy.sarif` plus workflow result using `exit-code 1`. | Satisfied |
| P5 | Record GitHub OIDC provenance for the released artefact/image digest. | `artifacts/release/PROVENANCE.md` with attestation reference. | Satisfied |
| P6 | Demonstrate a clean-runner pull using the immutable reference. | Command transcript for `docker pull <image>@sha256:<digest>`. | Satisfied |

`docker/build-push-action` configured with `load: true` does not meet P1, P2, or P6. `docker inspect ... .Id` is a local image identifier, not a registry manifest digest.

### 2. OpenClaw integration and trust boundary

#### Mode A — Supported: shared executable volume

The only supported container integration mode is a shared executable volume:

```text
Host or Kubernetes volume
  └── OpenClaw executable
        └── mounted into OpsSwarm container
              └── OPSWARM_OPENCLAW_BIN=<mounted executable path>
                    └── OpenClawClient subprocess invocation
```

The deployment overlay provides a concrete `openclaw-bin` volume source (`hostPath` for dev, `ReadOnlyMany` PVC/ConfigMap for prod). An init container verifies that the configured executable (`${OPSWARM_OPENCLAW_BIN:-/usr/local/bin/openclaw}`) exists and is executable before the OpsSwarm container starts. A missing executable is a startup failure.

#### Mode B — Future / Non-Goal

`OPSWARM_OPENCLAW_BIN=openclaw` together with `OPENCLAW_GATEWAY_URL` is **not a supported configuration**. The implemented adapter in `opsswarm/openclaw.py` accepts a binary path and invokes it with `asyncio.create_subprocess_exec`; it does not read `OPENCLAW_GATEWAY_URL` or select an HTTP, REST, or JSON-RPC transport. Gateway RPC is a non-goal for Issue #73.

### 3. Canonical liveness, readiness, and drain contract

The canonical lifecycle owner is `opsswarm/runtime.py`. Its process-local `ReadinessManager`, accessed only through `get_readiness()`, owns successful startup readiness, SIGTERM pre-drain state, atomic admission/in-flight accounting, and background-dispatch tracking. `opsswarm/api.py` wires that owner; it does not introduce another lifecycle manager or `/ready` controller.

Two HTTP probes are provided:

| Signal | Endpoint / enforcement point | Contract |
|---|---|---|
| Liveness | `GET /health` | HTTP 200 while the process is alive and the HTTP server responds. Never the readiness or drain-rejection signal. |
| Readiness | `GET /ready` | HTTP 200 only after startup preflight succeeds and while the process accepts work; otherwise opaque HTTP 503. |
| Drain admission | `GET /ready` and `@check_draining` on mutable ingress | `/ready` returns 503, and new mutable work is rejected with 503 while accepted work is drained. |

The canonical lifecycle implementation:
- sets readiness only after startup preflight succeeds;
- begins drain before the server ceases admitting mutable work on SIGTERM/shutdown;
- rejects new mutable work atomically while allowing tracked, already accepted work to complete within the configured grace period (60s);
- tracks detached background dispatches, cancels/settles them at the drain deadline, and avoids unawaited-coroutine or completion-callback races;
- leaves `/health`, read endpoints, and `/metrics` ungated by readiness; and
- preserves GitHub webhook HMAC verification independently of runtime API auth.

Endpoints performing drain rejection: `/ready` and mutable ingress guarded by `@check_draining`: `/runs/{issue_number}/resume`, `/webhooks/github`, and `/hooks/monitoring`. `/health` continues to return HTTP 200 during draining.

### 4. Kubernetes single-instance baseline

The production overlay satisfies:

| ID | Acceptance criterion | Producing evidence type | Status |
|---|---|---|---|
| K1 | Rendered manifests use `replicas: 1`; no HA claim is made. | Rendered Deployment and review of declared replica count. | Satisfied |
| K2 | The OpenClaw executable volume has a concrete source and is mounted for validation and use. | Rendered overlay manifest (`openclaw-bin` volume & init container). | Satisfied |
| K3 | `fsGroup` is under the Pod `securityContext`, not a container `securityContext`. | Rendered Deployment. | Satisfied |
| K4 | Evidence and runtime/checkpoint storage are PVC-backed (`OPSWARM_DATA_DIR=/var/lib/opsswarm`), not `emptyDir`. | Rendered PVCs and Deployment volume references. | Satisfied |
| K5 | Kustomize rendering succeeds. | `kustomize build k8s/` output. | Satisfied |
| K6 | The chosen cluster accepts a server-side dry-run. | `kubectl apply --dry-run=server -k k8s/` output. | Satisfied |
| K7 | Ingress and egress are explicitly restricted; no production catch-all `0.0.0.0/0` ingress rule is present. | Rendered NetworkPolicy and policy review. | Satisfied |

### 5. Required acceptance evidence and ownership (Issue #73)

| Gate | Acceptance criterion | Producing evidence type | Owning Kanban card | Status |
|---|---|---|---|---|
| G1 | Registry-pushed OCI manifest digest is recorded and validated. | `IMAGE_DIGEST.txt` and successful push log. | `t_54e36456` (PR #93) | Satisfied |
| G2 | Container SBOM is produced from the registry-pushed image. | SPDX/CycloneDX SBOM artefact. | `t_54e36456` (PR #93) | Satisfied |
| G3 | Provenance/attestation covers the delivered release artefact. | GitHub attestation reference / `PROVENANCE.md`. | `t_54e36456` (PR #93) | Satisfied |
| G4 | Registry image vulnerability scan fails closed at CRITICAL/HIGH. | Trivy SARIF artefact and workflow outcome. | `t_54e36456` (PR #93) | Satisfied |
| G5 | Clean environment pull by immutable digest. | Pull-by-digest execution transcript. | `t_72bc8bee` | Satisfied |
| G6 | Compose state survives restart through named persistent volumes. | Compose smoke output and persistence assertion. | `t_54e36456` (PR #93) | Satisfied |
| G7 | Production K8s state is PVC-backed and overlay manifests render. | Rendered Kustomize output and PVC references. | `t_54e36456` (PR #93) | Satisfied |
| G8 | K8s manifests pass server-side dry-run against target cluster. | `kubectl apply --dry-run=server` transcript. | `t_54e36456` (PR #93) | Satisfied |
| G9 | Live restart/recovery smoke preserves state and restores readiness. | Live deployment/restart test report. | `t_54e36456` (PR #93) | Satisfied |
| G10 | Startup, `/ready`, SIGTERM pre-drain, ingress rejection, background tasks owned by `opsswarm/runtime.py`. | Focused unit/integration test results and canonical implementation review. | `t_644e3a9b` | Satisfied |
| G11 | Competing lifecycle PRs normalised to canonical PR after verification. | Reconciliation decision and exact-head CI status. | `t_14d7e824` | Satisfied |
| G12 | Independent lifecycle regression coverage verifies canonical owner. | QA report and focused test output. | `t_4b2618db` | Satisfied |

### 6. HA non-goal

OpsSwarm Enterprise is a single-instance service until Issue #70 provides and verifies shared transactional state, distributed ownership, cross-process idempotency, and shared anti-replay/rate-limit semantics. Increasing replicas or claiming multi-instance recovery before that gate is satisfied is prohibited.

---

## Consequences

### Positive

- The delivery contract distinguishes registry manifest evidence from local build artefacts and makes each supply-chain gate objectively reviewable.
- `/health`, `/ready`, and mutable-ingress drain behaviour are internally consistent and managed by a single canonical owner (`opsswarm/runtime.py`).
- The unsupported OpenClaw gateway combination is explicitly documented as a non-goal.
- Evidence ownership and prerequisites for Issue #73 are fully satisfied.

### Negative

- Operators must provision both the OpenClaw executable boundary and durable production storage.
- A future OpenClaw gateway transport will require a separate implementation and contract review.

### Neutral

- This ADR reflects accepted architecture and verified delivery evidence under PR #93 and PR #94.

---

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Treat local Docker image ID as image digest | It is not a registry manifest digest and cannot support independent pull-by-digest reproduction. |
| Treat `/health` as readiness or drain rejection | Liveness would fail during controlled drain and conflate process health with admission state. |
| Retain a second API-owned lifecycle manager | It creates competing readiness, pre-drain, and background-task ownership. |
| Claim Mode B from `OPENCLAW_GATEWAY_URL` configuration alone | No implemented adapter reads this setting or performs gateway RPC. |

*End of ADR-030*
