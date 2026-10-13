# Day-0 FastAPI Cloud Run Deployment

Issue [#9](https://github.com/retailtwin-ai/retailtwin-ai/issues/9)

Reproducible, non-interactive deployment of the RetailTwin API to Cloud Run.
Prerequisites: Docker, Google Cloud SDK (`gcloud`), an active GCP project with billing
enabled and the **Cloud Run API** enabled.

> **Security posture:** non-root container (UID 10001), no service-account key files,
> no secrets baked in, no IAM widening. The default Compute Engine service account
> is used (Cloud Run-managed, short-lived tokens). Secrets live in Secret Manager
> and are injected at runtime via `--set-secrets`.

---

## 1. GCP Prerequisites (One-time)

```bash
# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  secretmanager.googleapis.com \
  containerregistry.googleapis.com \
  --project=retailtwin-ai-511002

# Create the runtime service account
gcloud iam service-accounts create retailtwin-runtime \
  --display-name="RetailTwin Cloud Run Runtime" \
  --project=retailtwin-ai-511002

# Grant it Cloud Run Invoker + Secret Accessor
gcloud projects add-iam-policy-binding retailtwin-ai-511002 \
  --member="serviceAccount:retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud secrets add-iam-policy-binding STORE_FIXTURE_PATH \
  --member="serviceAccount:retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## 2. Build and Push the Container

```bash
# Authenticate Docker to GCR (one-time)
gcloud auth configure-docker gcr.io

# Build (from repo root)
docker build -t retailtwin-api:local .

# Tag for GCR
docker tag retailtwin-api:local \
  gcr.io/retailtwin-ai-511002/retailtwin-api:t_1821a674

# Push
docker push gcr.io/retailtwin-ai-511002/retailtwin-api:t_1821a674
```

Expected output:
```
The push refers to repository [gcr.io/retailtwin-ai-511002/retailtwin-api]
…
t_1821a674: digest: sha256:<IMAGE_DIGEST> size: 856
```

---

## 3. Deploy to Cloud Run

```bash
gcloud run deploy retailtwin-api \
  --image gcr.io/retailtwin-ai-511002/retailtwin-api:t_1821a674 \
  --platform managed \
  --region us-central1 \
  --service-account=retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com \
  --no-allow-unauthenticated \
  --port 8080 \
  --min-instances 1 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60 \
  --set-secrets STORE_FIXTURE_PATH=store-fixture:latest \
  --set-secrets APP_ENV=APP_ENV:latest
```

> **Security note:** `--no-allow-unauthenticated` locks the service to IAM authentication.
> Use `gcloud run services add-iam-policy-binding` or the Console to grant specific
> principals (e.g. your frontend SA) the `run.invoker` role on `retailtwin-api`.

Expected output:
```
Deploying container to Cloud Run service [retailtwin-api] …
Setting IAM Policy......................................done
Creating Revision.....................................................................done
Routing traffic.....done
Done.
Service [retailtwin-api] revision [retailtwin-api-00001-wz4]
  has been deployed and is serving 100 percent of traffic.
Service URL: https://retailtwin-api-<hash>.us-central1.run.app
```

---

## 4. Verify the Deployment

> The service is private (no unauthenticated access). Use an identity token scoped to the service URL:
```bash
SERVICE_URL=https://retailtwin-api-<hash>.us-central1.run.app

# Obtain identity token scoped to the service URL for authenticated health check
TOKEN=$(gcloud auth print-identity-token --audiences="${SERVICE_URL}" --quiet)

curl -s -H "Authorization: Bearer ${TOKEN}" "${SERVICE_URL}/health"
curl -s -H "Authorization: Bearer ${TOKEN}" "${SERVICE_URL}/store" | python -m json.tool
```

Expected output:
```json
{
  "status": "ok",
  "service": "retailtwin-api",
  "environment": "development",
  "store_id": "store-001",
  "fixture_loaded": true
}
```

```json
{
  "store_id": "store-001",
  "context_version": "store-001:v1",
  "version": "v1",
  "products": [
    {
      "store_id": "store-001",
      "sku": "P001",
      "shelf_id": "A01",
      "slot_id": "A01-S01",
      "facings": 3,
      "shelf_quantity": 8,
      "backroom_quantity": 42,
      "version": 1
    }
  ]
}
```

### Revision Evidence

```bash
gcloud run revisions describe retailtwin-api-00001-wz4 \
  --region us-central1 --format=yaml | grep -E "name:|Image:|creationTimestamp:"
```

```
name: retailtwin-api-00001-wz4
creationTimestamp: '2026-10-12T07:53:19.600983Z'
Image: gcr.io/retailtwin-ai-511002/retailtwin-api@sha256:97a6d04…
Service account: retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com
```

---

## 5. Environment Variables (Runtime)

| Variable | Default | Notes |
|---|---|---|
| `PORT` | `8080` | Set by Cloud Run; do not override |
| `UVICORN_HOST` | `0.0.0.0` | Bind address |
| `UVICORN_PORT` | `8080` | Mirror PORT for uvicorn |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `STORE_FIXTURE_PATH` | from Secret Manager | Injected at runtime by Cloud Run |
| `STORE_ID` | `store-001` | Store scope |
| `APP_ENV` | `production` | Set via Secret Manager |

---

## 6. CI/CD Integration

The full production deploy job lives in `.github/workflows/api.yml`. Key configuration:

```yaml
deploy-cloud-run:
  needs: [build-test, e2e-smoke]
  runs-on: ubuntu-latest
  environment: production          # gates on main + CI green
  steps:
    - uses: actions/checkout@v4
    - uses: google-github-actions/auth@v2
      with:
        workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
        service_account: github-actions@retailtwin-ai-511002.iam.gserviceaccount.com
    # Build & push container …
    - name: Activate Secret Manager
      run: gcloud services enable secretmanager.googleapis.com --project=retailtwin-ai-511002
    - name: Deploy to Cloud Run
      id: deploy
      uses: google-github-actions/deploy-cloudrun@v2
      with:
        service: retailtwin-api
        region: us-central1
        service_account: retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com
        image: gcr.io/retailtwin-ai-511002/retailtwin-api:${{ github.sha }}
        allow_unauthenticated: false
        secrets: STORE_FIXTURE_PATH=store-fixture:latest
```

> **Verification step** uses `gcloud identity tokens sign-jwt` (or `generateIdToken` API) to
> acquire an OIDC token scoped to the service URL, so it works against the private service.

---

## 7. Production Hardening (Issue #34)

All production hardening features are implemented.

| Feature | Status | Details |
|---|---|---|
| Structured JSON logging | Done | Cloud Logging-compatible JSON per request/event |
| Correlation IDs | Done | `X-Correlation-ID` injected, echoed in response headers |
| Readiness probe | Done | `GET /ready` returns 503 when fixture unavailable |
| Liveness probe | Done | `GET /health` always 200 if container alive |
| Settings validation | Done | `APP_ENV`, `LOG_LEVEL` validated at startup |
| Production env flag | Done | `APP_ENV=production` sets `is_production=True` |
| Min-instances=1 | Done | Prevents cold-start; configured in CI and deploy script |
| Dedicated service account | Done | `retailtwin-runtime@…` — no default Compute SA |
| Secret Manager integration | Done | Runtime injection via `--set-secrets` |

### Readiness vs Liveness Separation

```
Cloud Run LB
    ├── /health  → liveness probe (always 200 if container alive)
    └── /ready   → readiness probe (200=serve, 503=drain)
```

The readiness probe returns 503 when the store fixture is unavailable, causing Cloud Run to drain traffic away from that instance. This is the correct behavior for a store-read-only service.

### Structured Logs

Every log line is a JSON object:

```json
{"message":"request.start","severity":"INFO","timestamp":"2026-10-12T09:00:00.000Z","correlation_id":"abc-123","method":"GET","path":"/ready","client_host":"192.168.0.1","service":"retailtwin-api","logger":"retailtwin_api.middleware","level":"INFO"}
```

Cloud Logging parses these automatically from container stdout.

---

## 8. Rollback

```bash
# List revisions
gcloud run revisions list --service retailtwin-api --region us-central1

# Route 100% traffic to a previous revision
gcloud run services update-traffic retailtwin-api \
  --to-revisions retailtwin-api-00001-wz3=100 \
  --region us-central1
```

---

## 9. Secret Manager Pattern

**Principle:** No secrets in source, in environment variables, or baked into container images. All secrets live in GCP Secret Manager and are injected at runtime.

### Create a secret

```bash
# One-time secret creation
gcloud secrets create STORE_FIXTURE_PATH --data-file=- <<< "data/schemas/store-state.example.json"
gcloud secrets create APP_ENV --data-file=- <<< "production"
gcloud secrets add-versions --data-file=- <<< "v1"  # default version
```

### Grant Cloud Run service account access

```bash
gcloud secrets add-iam-policy-binding STORE_FIXTURE_PATH \
  --member="serviceAccount:retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Deploy with secret injection

```bash
gcloud run deploy retailtwin-api \
  --image gcr.io/$PROJECT_ID/retailtwin-api:$TAG \
  --set-secrets STORE_FIXTURE_PATH=STORE_FIXTURE_PATH:latest \
  --set-secrets APP_ENV=APP_ENV:latest \
  --region us-central1
```

### Rotation

Create a new version; Cloud Run picks it up on the next cold-start (no re-deploy required):

```bash
gcloud secrets versions add STORE_FIXTURE_PATH --data-file=store-state.v2.json
# Next Cloud Run instance automatically reads :latest
```

### Local development

Locals use `.env` (gitignored) or environment variables — Secret Manager is **Cloud Run only**.

```
# .env (gitignored)
STORE_FIXTURE_PATH=data/schemas/store-state.example.json
APP_ENV=development
```

---

## 10. Exclusions

- Multi-service mesh / Istio hardening — tracked in issue #34
- Service-account key file creation — use workload identity federation instead
- IAM permission widening beyond the `retailtwin-runtime` service account
- Hardcoded secrets in environment variables — use Secret Manager with
  `--set-secrets STORE_FIXTURE_PATH=store-fixture:latest`

---

## Files Changed

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build; non-root runtime; uv dependency management |
| `apps/api/retailtwin_api/middleware.py` | Structured JSON logging + correlation ID middleware |
| `apps/api/retailtwin_api/routes.py` | Readiness probe `/ready`; correlation IDs in logs |
| `apps/api/retailtwin_api/settings.py` | Production env guard + settings validation |
| `apps/api/retailtwin_api/schemas.py` | `ReadyResponse`, `app_env` in `HealthResponse` |
| `apps/api/tests/test_health.py` | 12 tests: probes, correlation IDs, settings, logs |
| `.github/workflows/api.yml` | Production `deploy-cloudrun` job (on merge to main) |
| `scripts/deploy-cloudrun.sh` | Local deploy script with verification |
| `.env.example` | Production Cloud Run environment variable hints |
| `docs/deploy.md` | Production hardening docs, structured logging example |
