# ADR-030: Container Delivery Acceptance Contract

**Status:** Proposed

**Created:** 2026-10-21

**Review:** Required before closing Issue #73

**Related:** Issue #73, Issue #70, Issue #30

---

## Context

PR #93 (`feat/73-container-delivery`) introduced OCI image, Docker Compose, and
Kubernetes deployment artefacts. Review found that the artefacts and their
production claims are not yet supported by the required delivery evidence or by a
single canonical lifecycle implementation.

The material gaps are:

1. A local Docker image ID or `RepoDigests` from `load: true` is not an OCI
   registry manifest digest. Production delivery requires a registry-pushed
   immutable manifest digest and evidence derived from that image.
2. `OPSWARM_OPENCLAW_BIN` requires an explicit executable-volume boundary.
   Existing `OpenClawClient` is a subprocess adapter, not an HTTP/RPC gateway
   adapter.
3. `/health` must remain liveness-only. Startup readiness, SIGTERM pre-drain,
   mutable-ingress rejection, and background-dispatch tracking require one
   process-local owner, rather than competing API lifecycle controllers.
4. A production K8s deployment requires renderable and server-validated
   manifests, PVC-backed state, correctly scoped security context, and restricted
   network policy.
5. OpsSwarm remains a single-instance service until Issue #70 supplies and
   verifies shared transactional coordination.

This ADR is a proposed acceptance contract. It does not claim that Issue #73 has
been delivered. Acceptance requires both the PR #93 delivery evidence listed below
and the canonical lifecycle implementation.

---

## Decision

### 1. OCI publication and supply-chain contract

A release is acceptable only when its image has been pushed to a named OCI registry
and is identified by the resulting immutable **registry manifest digest**
(`sha256:` followed by 64 hexadecimal characters). A mutable tag, local image ID,
or image loaded only into the GitHub Actions runner is not equivalent evidence.

The delivery workflow must:

| ID | Acceptance criterion | Producing evidence type |
|---|---|---|
| P1 | Push the OCI image to the registry with a version tag and a pinned SHA tag. | Workflow push log and registry reference. |
| P2 | Capture and validate the registry manifest digest from the push output before it is used. | `artifacts/release/IMAGE_DIGEST.txt`; value matches `^sha256:[0-9a-f]{64}$`. |
| P3 | Generate an SPDX or CycloneDX SBOM from the registry-pushed image. | `artifacts/release/sbom.spdx.json` and/or `sbom.cdx.json`. |
| P4 | Scan the registry-pushed image for CRITICAL/HIGH vulnerabilities and fail closed. | `artifacts/release/trivy.sarif` plus workflow result using `exit-code 1`. |
| P5 | Record GitHub OIDC provenance for the released artefact/image digest. | `artifacts/release/PROVENANCE.md` with attestation reference. |
| P6 | Demonstrate a clean-runner pull using the immutable reference. | Command transcript for `docker pull <image>@sha256:<digest>`. |

`docker/build-push-action` configured with `load: true` does not meet P1, P2, or
P6. `docker inspect ... .Id` is a local image identifier, not a registry manifest
digest; it must not be recorded as release-digest evidence.

### 2. OpenClaw integration and trust boundary

#### Mode A — supported: shared executable volume

The only supported container integration mode is a shared executable volume:

```text
Host or Kubernetes volume
  └── OpenClaw executable
        └── mounted into OpsSwarm container
              └── OPSWARM_OPENCLAW_BIN=<mounted executable path>
                    └── OpenClawClient subprocess invocation
```

The deployment overlay must provide a concrete `openclaw-bin` volume source. An
init container must verify that the configured executable exists and is executable
before the OpsSwarm container starts. A missing executable is a startup failure;
it must not degrade silently.

#### Mode B — future / unsupported

`OPSWARM_OPENCLAW_BIN=openclaw` together with `OPENCLAW_GATEWAY_URL` is **not a
supported configuration**. The implemented adapter in `opsswarm/openclaw.py`
accepts a binary path and invokes it with `asyncio.create_subprocess_exec`; it does
not read `OPENCLAW_GATEWAY_URL` or select an HTTP, REST, or JSON-RPC transport.
A future gateway adapter requires its own implementation, authentication contract,
and ADR update. Until then, deployment documentation must not present this
combination as functional.

### 3. Canonical liveness, readiness, and drain contract

The canonical lifecycle owner is `opsswarm/runtime.py`. Its process-local
`ReadinessManager`, accessed only through `get_readiness()`, owns successful
startup readiness, SIGTERM pre-drain state, atomic admission/in-flight accounting,
and background-dispatch tracking. `opsswarm/api.py` wires that owner; it must not
introduce another lifecycle manager, app state singleton, task registry, or `/ready`
controller.

Only two HTTP probes are provided by the canonical contract; no third probe is
assumed:

| Signal | Endpoint / enforcement point | Contract |
|---|---|---|
| Liveness | `GET /health` | HTTP 200 while the process is alive and the HTTP server responds. It is never the readiness or drain-rejection signal. |
| Readiness | `GET /ready` | HTTP 200 only after startup preflight succeeds and while the process accepts work; otherwise opaque HTTP 503. |
| Drain admission | `GET /ready` and `@check_draining` on mutable ingress | `/ready` returns 503, and new mutable work is rejected with 503 while accepted work is drained. |

The canonical lifecycle implementation must:

- set readiness only after its startup preflight succeeds;
- begin drain before the server ceases admitting mutable work on SIGTERM/shutdown;
- reject new mutable work atomically while allowing tracked, already accepted work
  to complete within the configured bounded grace period;
- track detached background dispatches, cancel/settle them at the drain deadline,
  and avoid an unawaited-coroutine or completion-callback race;
- leave `/health`, read endpoints, and `/metrics` ungated by readiness; and
- preserve GitHub webhook HMAC verification independently of runtime API auth.

The endpoints that perform drain rejection are `/ready` and mutable ingress guarded
by `@check_draining`: `/runs/{issue_number}/resume`, `/webhooks/github`, and
`/hooks/monitoring`. `/health` continues to return HTTP 200 while the process is
alive, including during draining.

### 4. Kubernetes single-instance baseline

A production overlay must meet all of these conditions:

| ID | Acceptance criterion | Producing evidence type |
|---|---|---|
| K1 | The rendered manifests use `replicas: 1`; no HA claim is made. | Rendered Deployment and review of the declared replica count. |
| K2 | The OpenClaw executable volume has a concrete source and is mounted for validation and use. | Rendered overlay manifest. |
| K3 | `fsGroup` is under the Pod `securityContext`, not a container `securityContext`. | Rendered Deployment. |
| K4 | Evidence and runtime/checkpoint storage are PVC-backed, not `emptyDir`. | Rendered PVCs and Deployment volume references. |
| K5 | Kustomize rendering succeeds. | `kustomize build k8s/` output. |
| K6 | The chosen cluster accepts a server-side dry-run. | `kubectl apply --dry-run=server -k k8s/` output. |
| K7 | Ingress and egress are explicitly restricted; no production catch-all `0.0.0.0/0` ingress rule is present. | Rendered NetworkPolicy and policy review. |

### 5. Required acceptance evidence and ownership

Every row is an acceptance criterion, not a claim that evidence already exists.
Issue #73 may be accepted only when all applicable evidence is produced and
reviewed, and the canonical lifecycle implementation is available.

| Gate | Acceptance criterion | Producing evidence type | Owning Kanban card |
|---|---|---|---|
| G1 | Registry-pushed OCI manifest digest is recorded and validated. | `IMAGE_DIGEST.txt` and successful push log. | `t_e0cbc06c` (PR #93) |
| G2 | Container SBOM is produced from the registry-pushed image. | SPDX/CycloneDX SBOM artefact. | `t_e0cbc06c` (PR #93) |
| G3 | Provenance/attestation covers the delivered release artefact. | GitHub attestation reference / `PROVENANCE.md`. | `t_e0cbc06c` (PR #93) |
| G4 | Registry image vulnerability scan fails closed at CRITICAL/HIGH. | Trivy SARIF artefact and workflow outcome. | `t_e0cbc06c` (PR #93) |
| G5 | A clean environment can pull the published image by immutable digest. | Pull-by-digest execution transcript. | `t_72bc8bee` |
| G6 | Compose state survives a restart through named persistent volumes. | Compose smoke output and persistence assertion. | `t_e0cbc06c` (PR #93) |
| G7 | Production K8s state is PVC-backed and overlay manifests render. | Rendered Kustomize output and PVC references. | `t_e0cbc06c` (PR #93) |
| G8 | K8s manifests pass server-side dry-run against the target cluster. | `kubectl apply --dry-run=server` transcript. | `t_e0cbc06c` (PR #93) |
| G9 | A live restart/recovery smoke preserves required state and restores readiness. | Live deployment/restart test report. | `t_e0cbc06c` (PR #93) |
| G10 | Startup, `/ready`, SIGTERM pre-drain, ingress rejection, and background-task tracking have one runtime owner. | Focused unit/integration test results and canonical implementation review. | `t_d625c7b9` |
| G11 | The competing lifecycle PRs are normalised to one canonical PR after verification. | Reconciliation decision and exact-head CI status. | `t_9758bb0d` |
| G12 | Independent lifecycle regression coverage verifies the canonical owner. | QA report and focused test output. | `t_4b2618db` |

### 6. HA non-goal

OpsSwarm Enterprise is a single-instance service until Issue #70 provides and
verifies shared transactional state, distributed ownership, cross-process
idempotency, and shared anti-replay/rate-limit semantics. Increasing replicas or
claiming multi-instance recovery before that gate is satisfied is prohibited.

---

## Consequences

### Positive

- The delivery contract distinguishes registry manifest evidence from local build
  artefacts and makes each supply-chain gate objectively reviewable.
- `/health`, `/ready`, and mutable-ingress drain behaviour are internally
  consistent and have one stated lifecycle owner.
- The unsupported OpenClaw gateway combination cannot be mistaken for a supported
  production mode.
- Evidence ownership and prerequisites for Issue #73 are explicit.

### Negative

- Container delivery remains unaccepted until external registry, cluster, and live
  recovery evidence is produced; documentation alone cannot satisfy those gates.
- Operators must provision both the OpenClaw executable boundary and durable
  production storage.
- A future OpenClaw gateway transport will require a separate implementation and
  contract review.

### Neutral

- This is a documentation-only proposed ADR. It neither changes production
  artefacts nor asserts that any required check has been run.

---

## Alternatives considered

| Alternative | Rejected because |
|---|---|
| Treat local Docker image ID as image digest | It is not a registry manifest digest and cannot support independent pull-by-digest reproduction. |
| Treat `/health` as readiness or drain rejection | Liveness would fail during controlled drain and conflate process health with admission state. |
| Retain a second API-owned lifecycle manager | It creates competing readiness, pre-drain, and background-task ownership. |
| Claim Mode B from `OPENCLAW_GATEWAY_URL` configuration alone | No implemented adapter reads this setting or performs gateway RPC. |

*End of ADR-030*
