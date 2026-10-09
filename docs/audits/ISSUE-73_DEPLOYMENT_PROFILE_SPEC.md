# Issue #73 deployment-profile architecture audit and implementation specification

**Status:** implementation-ready design; no deployment artifacts are introduced by this audit.

**Audited revision:** `ade851b` (`origin/master` at audit time)

**Scope:** OCI image, local Compose, Kubernetes profile, deployment security, lifecycle, and delivery evidence for [Issue #73](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/73).

## 1. Executive decision

Ship a **single-replica, file-backed container profile first**. It must make its singleton limit explicit and must not use Kubernetes scaling, a HorizontalPodAutoscaler, or `replicas > 1`. Multi-replica/HA support is blocked on [Issue #70](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/70), which must provide transactional shared state, ownership leases, compare-and-swap revisions, and shared replay/rate-limit coordination.

The initial profile runs the existing OpenClaw Gateway-backed CLI as an **external dependency**. The OpsSwarm image must not contain OpenClaw, its gateway configuration, agent workspaces, model-provider credentials, or enterprise-tool credentials. This follows the distribution boundary in `docs/guides/RELEASE_POLICY.md`: config, OpenClaw assets, skills, and runtime data are external deployment inputs.

## 2. Repository-grounded current contract

| Concern | Verified current behaviour | Deployment consequence |
|---|---|---|
| Application | FastAPI is constructed in `opsswarm/api.py`; documented launch is `uvicorn opsswarm.api:app --host 0.0.0.0 --port 8088`. | Container entrypoint uses that command with one worker. |
| Liveness | `GET /health` is public and returns `{ok, version, architecture}` (`opsswarm/api.py:149-151`). | Use `/health` only for liveness/startup. It does not verify dependencies or write safety. |
| Readiness | No `/ready` route or readiness dependency check currently exists. | Do not configure readiness as if it proves GitHub/OpenClaw/storage availability. Add `/ready` in a prerequisite implementation card. |
| Auth | Production startup calls `_ensure_production_auth_config()` (`opsswarm/api.py:135-141`); runtime API scopes use `OPSWARM_RUNTIME_SECRET` or `OPSWARM_API_KEY_<SCOPE>`. GitHub webhooks use independent `GITHUB_WEBHOOK_SECRET` HMAC. | Set `APP_ENV=production`; inject secrets only at runtime. A failed startup must prevent traffic admission. |
| State | `RunStore` writes `runtime-data/runs/*.json` using temp-file + `os.replace` (`opsswarm/store.py:31-71`). Evidence is append-only JSONL under `runtime-data/evidence/`, uses durable `fsync`, and has a per-run cross-process advisory lock (`opsswarm/evidence.py:72-91`, `180-271`). | Mount a durable writable volume at `OPSWARM_DATA_DIR`; root filesystem can be read-only. Do not treat atomic file replacement/evidence locking as a multi-instance coordination protocol. |
| Process coordination | Orchestrator run and command locks are process-local `asyncio.Lock`s (`opsswarm/orchestrator.py:143-193`); auth anti-replay and monitoring rate limiter are in-memory. | Exactly one OpsSwarm process/pod is supported until #70. `uvicorn --workers` must not be used. |
| OpenClaw | The client invokes `openclaw agent --agent ... --session-key ... --message-file ... --json` as a subprocess (`opsswarm/openclaw.py:121-132`). `openclaw/README.md` requires a separately installed/configured Gateway. | Image only needs a configurable `OPSWARM_OPENCLAW_BIN` path; it must be supplied by a compatible external runtime arrangement. The initial deployment must document and test the selected external command-access contract. |
| Metrics | `/metrics` requires `opsswarm:admin`; metrics and rate-limit state are in-memory (`docs/guides/METRICS_INTEGRATION.md`). | Put metrics behind a network policy/reverse proxy; scraping is not an availability/readiness signal. |
| Release/SBOM | Release CI builds Python wheel/sdist, SBOM, checksums and GitHub attestations; Security CI produces an SBOM for locked runtime dependencies. Neither builds/scans an OCI image. | Add an image-specific CI path; do not claim the existing Python SBOM/provenance covers a container image. |

No Dockerfile, Compose file, Helm chart, Kustomization, Kubernetes manifest, or image workflow exists at the audited revision. `deploy/prometheus.yml` is the only deployment asset found. The metrics guide refers to `deploy/systemd/opsswarm.service`, but that file is absent at this revision; that stale reference must be corrected or restored by the deployment-documentation card.

## 3. OCI image specification

### 3.1 Build and runtime boundary

1. Use a pinned Python 3.11 base image digest in both builder and runtime stages. Record base-image digest and Python version as OCI labels.
2. Builder stage:
   - copy only package metadata, `requirements.lock`, package source, and the files required to build the wheel;
   - install the hash-locked runtime graph with `pip --require-hashes -r requirements.lock` into a virtual environment;
   - build the wheel using the pinned release tooling;
   - run `pip check`.
3. Runtime stage:
   - copy only the built wheel and its installed runtime environment;
   - install the wheel without source checkout, test suite, `.git`, `openclaw/`, `skills/`, `config/`, scripts, or CI material;
   - expose TCP 8088 and launch exactly one Uvicorn worker;
   - use an exec-form command so SIGTERM reaches Uvicorn directly.
4. Do not add a Node/npm build stage or runtime dependency.

The image must carry no default production config. It must receive `OPSWARM_CONFIG` pointing at an externally mounted/read-only config file, and `OPSWARM_DATA_DIR` pointing at its one writable state location.

### 3.2 Identity and filesystem

- Create a named, fixed non-root user/group (for example UID/GID `10001`) in the final stage. Set `USER` before `ENTRYPOINT`.
- Set `HOME` to a writable path only if the selected OpenClaw invocation needs it; otherwise use a non-writable home and document it.
- Run with `readOnlyRootFilesystem: true` / `--read-only`.
- The only mandatory writable path is `${OPSWARM_DATA_DIR}`. Initial profile default: `/var/lib/opsswarm`; it contains `runs/`, `evidence/`, retained `.lock` files, and temporary atomic-write files.
- Add writable `emptyDir`/tmpfs paths only after proving a specific library needs them (for example `/tmp`). Do not broadly mount the root filesystem writable.
- Container user must own the data volume before process start. Kubernetes should use `runAsUser`, `runAsGroup`, `runAsNonRoot`, and an appropriate `fsGroup`; Compose should initialise volume ownership without granting root to the app process.
- Drop Linux capabilities, set `allowPrivilegeEscalation: false`, and use the runtime-default seccomp profile. Do not mount a Docker socket, host paths, or service-account token unless a separately approved contract requires it.

### 3.3 OpenClaw integration decision

The first supported profile is **external OpenClaw**:

- OpsSwarm receives an executable path via `OPSWARM_OPENCLAW_BIN` and invokes it using the existing CLI contract.
- The deploying platform owns compatible Gateway lifecycle, OpenClaw configuration, agent workspaces, model credentials, and enterprise tool credentials.
- A sidecar is not part of the first delivery because the repository has no containerised Gateway contract, no health protocol for it, and no declared writable-path/credential model for its workspaces.
- An in-image OpenClaw installation is prohibited in the first delivery because it would blur release boundaries and copy external credentials/assets into the image.

A later sidecar/external-service profile requires an ADR covering authentication, shared workspace/data paths, lifecycle ordering, failure propagation, image provenance, and least-privilege credentials.

## 4. Single-replica safety statement and #70 gate

The initial container/Compose/Kubernetes deployment is safe only as **one Uvicorn process in one OpsSwarm replica** with one durable `OPSWARM_DATA_DIR` volume. It may be restarted, but not actively replicated.

The reason is concrete: `RunStore` has no cross-process revision/CAS or transaction; run and command locks are process-local; duplicate webhook/command bookkeeping is stored in local run snapshots; anti-replay and monitoring rate limiting are memory-local. Two instances can therefore diverge, overwrite run state, or perform duplicate external effects. Evidence locking alone does not solve run ownership.

Until #70 is delivered and independently verified:

- Compose must set no scale support and document `--scale opsswarm=1` as unsupported.
- Kubernetes `Deployment.spec.replicas` must equal `1`; no HPA, leader-election substitute, rolling surge, or PDB implying availability across replicas.
- Set `strategy: Recreate` for the first Kubernetes Deployment so rollout does not temporarily run old and new pods together against the same file-backed data volume.
- A PDB is optional only as `minAvailable: 0`; `minAvailable: 1` does not create HA and can block voluntary operations. Document it as maintenance protection, not availability.
- Do not use a `ReadWriteMany` filesystem as a workaround for #70.

What must wait for #70: replica count greater than one, rolling updates with overlap, autoscaling, distributed readiness based on shared state, production PostgreSQL/Redis resource manifests, shared idempotency/lease checks, and HA recovery/runbooks.

## 5. Compose profile scope

Provide a minimal `compose.yaml` plus a commented/optional observability example; it is an operator convenience profile, not an HA topology.

Required service contract:

- `image` uses a released immutable image digest; development build support, if included, must be a separate override file.
- `user` is the image non-root UID:GID; `read_only: true`; `cap_drop: [ALL]`; `security_opt: [no-new-privileges:true]`; a bounded `tmpfs: /tmp` only if validation proves it is needed.
- Mount three externally supplied inputs read-only: production config, OpenClaw command/runtime integration mount (if a local wrapper is used), and any public CA bundle referenced by `OPSWARM_GITHUB_CA_BUNDLE`.
- Mount one named/local durable volume at `/var/lib/opsswarm`; set `OPSWARM_DATA_DIR=/var/lib/opsswarm`.
- Inject `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, and runtime API secret/key using Compose secrets or an operator secret manager integration. Do not use committed `.env`, `environment:` literals, or build args for secret values.
- Set `APP_ENV=production`, `OPSWARM_CONFIG=/etc/opsswarm/production.yaml`, and explicit `OPSWARM_OPENCLAW_BIN`.
- Publish the service port only to the trusted reverse-proxy/host network. `/metrics` remains authenticated and must not be world-readable.
- Include a liveness healthcheck to `/health`; do not call an absent `/ready` endpoint.
- Include `stop_grace_period: 45s` (or a documented value greater than the maximum accepted graceful-drain budget) and `restart: unless-stopped`; this is restart behaviour, not HA.

Prometheus remains external. Its bearer credential must be supplied from a protected file/secret path, consistent with `deploy/prometheus.yml` and the metrics guide.

## 6. Kubernetes profile scope

Use plain, reviewable base manifests under `deploy/kubernetes/` in the first implementation. Do not introduce Helm solely for templating; choose Helm or Kustomize in a later card only if environment variation justifies it.

Required objects:

1. `Namespace` example or documented target namespace (no application secrets committed).
2. `ConfigMap` for non-secret production YAML and optional public CA bundle reference. Configuration must not contain token values.
3. Secret **reference contract**, not a committed `Secret` value manifest. Operators create `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, `OPSWARM_RUNTIME_SECRET` or scoped API keys in their approved secret manager/Kubernetes Secret workflow.
4. `PersistentVolumeClaim` for single-writer runtime data. StorageClass/access mode are operator inputs; use a single-writer access mode. A reclaim/backup/retention decision is required before deletion of data.
5. `Deployment` with one replica, `Recreate` strategy, the non-root/read-only security context, explicit `/var/lib/opsswarm` volume, and only required config/CA mounts.
6. ClusterIP `Service` exposing 8088. Ingress/TLS is platform-owned; if an Ingress example is later supplied, it must enforce TLS and restrict public endpoint surface to the GitHub webhook route as appropriate.
7. `NetworkPolicy` templates described below.
8. Optional PDB with `minAvailable: 0` only, clearly labelled single-replica maintenance protection.

Probe specification until readiness exists:

```text
startupProbe: GET /health, initialDelaySeconds=0, periodSeconds=5, failureThreshold=24
livenessProbe: GET /health, periodSeconds=10, timeoutSeconds=2, failureThreshold=3
readinessProbe: not supplied until /ready has an explicit fail-closed contract
terminationGracePeriodSeconds: 45
```

The health contract currently proves only that the HTTP process is serving. Do not make a liveness probe depend on GitHub, OpenClaw, or a mounted secret: restarting on a transient dependency outage can amplify an incident.

## 7. Readiness, drain, and SIGTERM specification

### 7.1 Required follow-up runtime contract

Before Kubernetes production readiness is claimed, add `GET /ready` with this contract:

- `200` only when startup validation completed, required auth configuration is loaded, configured data path is writable, and the service is accepting new work.
- `503` when startup is incomplete, termination drain has started, required configuration/secret validation failed, or the selected shared-coordination backend is unavailable in an eventual HA profile.
- Do not make the initial single-node readiness endpoint synchronously call GitHub or OpenClaw on every probe. Those are remote dependencies with their own typed failures and circuit-breaker semantics.
- Expose no secret, token, path, or raw dependency error in the body.

### 7.2 Termination behaviour

The current API has startup validation but no shutdown/drain handler. The implementation card must add it before making a graceful-shutdown guarantee:

1. On SIGTERM, set internal draining state first; `/ready` changes to `503` so the orchestrator/load balancer stops sending new requests.
2. Reject newly arriving mutation-capable webhook/monitoring/resume work with a retry-safe unavailable response after drain starts. Existing background `asyncio.create_task()` work must be accounted for; it cannot be silently abandoned or accepted after the drain decision.
3. Allow bounded in-flight request handling and persistence flush, bounded by `terminationGracePeriodSeconds`.
4. Persist/reconcile any command in the execution crash window as `UNKNOWN`, never retry an ambiguous external side effect automatically.
5. Exit non-zero only when graceful completion cannot be achieved; Kubernetes restart/recovery then follows existing reconciliation semantics.

The exact budget must be compatible with the configured OpenClaw call timeout (production config defaults to 600 seconds). A 45-second pod grace period cannot promise an in-flight 600-second OpenClaw action finishes. The first delivery must either bound/cancel active work on drain and make it recoverable, or set/document a larger termination budget. It must not claim both quick termination and completion of arbitrary 600-second work.

## 8. Secrets, configuration, and network policy

### 8.1 Configuration boundary

| Category | Delivery mechanism | Examples |
|---|---|---|
| Non-secret config | Read-only ConfigMap/mounted file | policy, labels, GitHub allowed origins, OpenClaw profiles, budgets, tool allowlist path |
| Secret config | Secret manager injection or Kubernetes Secret reference | `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, `OPSWARM_RUNTIME_SECRET`, scoped API keys |
| Public trust data | Read-only ConfigMap/volume | enterprise CA bundle referenced by `OPSWARM_GITHUB_CA_BUNDLE` |
| Mutable state | Durable PVC/Compose volume | `OPSWARM_DATA_DIR/runs`, `evidence`, lock and temporary write files |
| OpenClaw assets | External runtime/operator-owned mounted contract | Gateway config, workspaces, model credentials, enterprise tool credentials |

Never place any secret in a Dockerfile, build arg, OCI label, image layer, `ConfigMap`, committed manifest, CI log, test fixture, GitHub release asset, or SBOM metadata.

### 8.2 Network policy guidance

Default deny ingress and egress, then explicitly permit:

- ingress from the organisation's TLS reverse proxy/GitHub webhook path to TCP 8088;
- ingress from the approved metrics scraper to TCP 8088 only if `/metrics` is exposed directly; bearer authentication remains mandatory;
- egress DNS to the cluster DNS resolver;
- egress HTTPS to the exact configured `github.origins` / `OPSWARM_GITHUB_ORIGINS` hosts (GitHub.com or approved GHES);
- egress only to the selected external OpenClaw Gateway/command transport and approved enterprise-tool endpoints when the architecture establishes those flows.

A `NetworkPolicy` cannot express FQDN allowlisting portably. Pair it with the CNI/service-mesh/egress gateway control used by the platform, and keep the application-level GitHub origin allowlist enabled.

## 9. Resources and reliability guidance

Initial requests/limits must be explicit but are capacity inputs, not universal defaults. Begin with a conservative profile such as:

```text
requests: cpu 250m, memory 512Mi
limits:   cpu 1,    memory 1Gi
```

Load-test real incident concurrency and OpenClaw subprocess memory use before raising the configured `max_parallel_specialists` or lowering memory. Set an ephemeral-storage limit if the platform supports it because prompt files use the OS temporary directory. Use a data-volume quota and backup/retention policy; never delete the state volume during routine cleanup without confirmed migration/retention approval.

The image should log to stdout/stderr in structured/redacted form. The existing application log sanitisation is not permission to export secrets; collector configuration must preserve access control and retention policy.

## 10. CI, release, supply-chain, and security evidence

Add a dedicated image workflow/job, separated from the Python wheel release job. It must:

1. Build from a clean checkout using the locked dependency path and pinned base image digest.
2. Verify the final image's declared non-root user, `/health` response, read-only-root operation, and data-path writability under the intended UID.
3. Assert final image contents exclude `.git`, test files, `config/`, `openclaw/`, `skills/`, `.env`, and known secret patterns. Use layer inspection as well as filesystem inspection.
4. Generate an OCI image SBOM (SPDX or CycloneDX) covering OS and language packages; validate public artifact text using the existing artifact validator or a specifically extended, reviewed equivalent.
5. Scan the image with a pinned scanner and fail on the same CRITICAL/HIGH policy used by Security CI, with only documented time-bounded waivers.
6. Push by immutable digest, record the digest, and sign/attest the digest using GitHub OIDC provenance. Attach/retain SBOM, scan summary, digest, and attestation reference as release evidence.
7. Keep image publishing gated by the existing `CI` and `Security CI` success for the exact source commit. A Python wheel SBOM and attestation do not substitute for image evidence.
8. Render and validate Kubernetes manifests in CI with a pinned renderer/schema validator. Validate Compose syntax with a pinned Docker/Compose or compatible implementation.

Do not grant broad registry or cluster credentials to pull-request workflows. Publish only from a protected release path with least-privilege, OIDC federation where supported, and immutable tags/digests.

## 11. Required validation matrix

| Validation | Concrete command / assertion | Acceptance |
|---|---|---|
| Python baseline | `python -m pytest -q` and `python -m build` | Existing application contract stays green. |
| Locked image build | `docker build --pull --no-cache -t opsswarm:test .` | Build succeeds from clean checkout; record base/image digests. |
| Non-root | `docker image inspect opsswarm:test --format '{{.Config.User}}'` and runtime `id -u` | Non-zero fixed UID; no root process. |
| Read-only root | `docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m -v opsswarm-data:/var/lib/opsswarm ...` | Process starts with only documented writable paths. |
| Liveness | `curl -fsS http://127.0.0.1:8088/health` | Exact documented JSON contract and HTTP 200. |
| Auth failure | start with `APP_ENV=production` and no runtime auth secret/key | Process refuses startup; it must not bind 8088. |
| State durability | create a safe test run/evidence fixture, restart same one-replica container with same data volume | Run/evidence are retained and chain verification passes. |
| Singleton guard | Compose scale attempt and rendered Kubernetes Deployment inspection | Documented/tested one replica; no HPA; Recreate strategy. |
| Shutdown | send `docker stop --time <chosen-budget>` during a controlled in-flight request | Readiness goes unavailable before termination; no new unsafe work accepted; outcome is durable/recoverable. Requires `/ready` work first. |
| Compose | `docker compose -f compose.yaml config --quiet` | Render succeeds and contains no literal secret values. |
| Kubernetes | `kustomize build deploy/kubernetes | kubeconform -strict -summary` (or pinned equivalent) | All manifests render and validate; policy checks enforce non-root, read-only root, resource limits, one replica, and no secret literals. |
| Image SBOM/scan/provenance | CI artifacts plus `gh attestation verify <image-or-supported-subject> --repo vinhphan812/OpsSwarm-Enterprise` | Digest, SBOM, scan and provenance are present for the released image. |

Commands requiring Docker, Kubernetes access, registry credentials, or actual production secrets are CI/platform validation steps, not claimed as executed by this audit.

## 12. Recommended follow-up card graph

1. **Runtime lifecycle/readiness contract** — assignee: `dev-android`; parent: this audit. Implement `/ready`, drain state, tracked background work, SIGTERM semantics, and focused tests. This is the prerequisite for production readiness probes.
2. **OCI + Compose single-node profile** — assignee: `dev-ops`; parents: this audit and card 1. Add Dockerfile, `.dockerignore`, Compose profile, config/secret/data-volume contracts, image tests, and docs. Explicitly preserve the one-replica rule.
3. **Kubernetes single-node profile** — assignee: `dev-ops`; parents: cards 1 and 2. Add base manifests, PVC/service/network policy/security context/resources, render/schema/policy validation, and operator guide. No HPA or multi-replica claim.
4. **Image supply-chain CI/release evidence** — assignee: `dev-ops`; parent: card 2. Add immutable image build/push, OCI SBOM, vulnerability scan, provenance and release evidence, with no production runtime dependency added to the Python package.
5. **HA coordination backend** — assignee: `dev-architect` followed by `dev-android`; parent: Issue #70 decision. Only after its cross-process tests and operations guide pass may a follow-up card change replicas/rollouts/PDB/HPA to HA semantics.
6. **Deployment documentation review** — assignee: `dev-pm`; parents: cards 2-4. Update installation, operations, security, and metrics references, including the stale systemd-unit reference found in this audit.

The implementation cards must use a normal delivery branch and PR; this audit intentionally changes no deployment, CI, or runtime implementation files.
