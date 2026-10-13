# Day-0 FastAPI Cloud Run Deployment

Issue [#9](https://github.com/retailtwin-ai/retailtwin-ai/issues/9)

Reproducible, non-interactive deployment of the RetailTwin API to Cloud Run.
Prerequisites: Docker, Google Cloud SDK (`gcloud`), an active GCP project with billing
enabled and the **Cloud Run API** enabled.

> **Security posture:** non-root container (UID 10001), no service-account key files,
> no secrets baked in. A dedicated runtime service account
> (`retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com`) is used so IAM
> permissions are scoped to this service alone. Secrets live in Secret Manager
> and are injected at runtime via `--set-secrets`. Traffic is authenticated
> only — no public internet access (`--no-allow-unauthenticated`).

---

## 1. Build and Push the Container

```bash
# Authenticate Docker to Artifact Registry (one-time)
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build (from repo root)
docker build -t retailtwin-api:local .

# Tag for Artifact Registry
docker tag retailtwin-api:local \
  us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api:t_1821a674

# Push
docker push us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api:t_1821a674
```

Expected output:
```
The push refers to repository [us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api]
…
t_1821a674: digest: sha256:<IMAGE_DIGEST> size: 856
```

---

## 2. Deploy to Cloud Run

```bash
gcloud run deploy retailtwin-api \
  --image us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api:t_1821a674 \
  --platform managed \
  --region us-central1 \
  --no-allow-unauthenticated \
  --service-account retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com \
  --port 8080 \
  --min-instances 0 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60
```

> **Day-0 access decision:** `--no-allow-unauthenticated` enforces that only
> authenticated traffic (e.g. via Identity-Aware Proxy, Cloud Armor, or a
> service-to-service caller using the runtime SA) reaches the service.
> Add `--allow-unauthenticated` or an IAP/Cloud Armor policy only after the
> service is validated; track that step in issue #34.

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

## 3. Verify the Deployment

```bash
# Health check
curl -s https://<SERVICE_URL>/health

# Store read
curl -s https://<SERVICE_URL>/store | python -m json.tool
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
Image: us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api@sha256:97a6d04…
Service account: retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com
```

---

## 4. Environment Variables (Runtime)

| Variable | Default | Notes |
|---|---|---|
| `PORT` | `8080` | Set by Cloud Run; do not override |
| `UVICORN_HOST` | `0.0.0.0` | Bind address |
| `UVICORN_PORT` | `8080` | Mirror PORT for uvicorn |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `STORE_FIXTURE_PATH` | `data/schemas/store-state.example.json` | Day-0 read model |
| `STORE_ID` | `store-001` | Store scope |
| `APP_ENV` | `development` | Reported by `/health` |

---

## 5. CI/CD Integration

In GitHub Actions, add a job after tests pass:

```yaml
deploy-cloud-run:
  needs: [test]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: docker/setup-buildx-action@v3
    - id: auth
      uses: google-github-actions/auth@v2
      with:
        workload_identity_provider: projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL>/providers/<PROVIDER>
        service_account: <SA>@retailtwin-ai-511002.iam.gserviceaccount.com
    - uses: docker/build-push-action@v5
      with:
        push: true
        tags: us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api:${{ github.sha }}
    - name: Deploy to Cloud Run
      uses: google-github-actions/deploy-cloudrun@v2
      with:
        service: retailtwin-api
        region: us-central1
        image: us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api:${{ github.sha }}
        service_account: retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com
        # Day-0: authenticated traffic only. Open to public or add IAP in issue #34.
        # allow_unauthenticated: false  # default; shown for documentation
        port: 8080
        memory: 512Mi
        cpu: 1
        max_instances: 10
    - name: Health check
      run: |
        curl -f https://${{ env.SERVICE_URL }}/health || exit 1
```

---

## 6. Rollback

```bash
# List revisions
gcloud run revisions list --service retailtwin-api --region us-central1

# Route 100% traffic to a previous revision
gcloud run services update-traffic retailtwin-api \
  --to-revisions retailtwin-api-00001-wz3=100 \
  --region us-central1
```

---

## Exclusions (do not attempt in this PR)

- Multi-service mesh / Istio hardening — tracked in issue #34
- Service-account key file creation — use workload identity federation instead
- Opening `--no-allow-unauthenticated` to public or adding IAP/Cloud Armor — tracked in issue #34
- Hardcoded secrets in environment variables — use Secret Manager with
  `--set-secrets STORE_FIXTURE_PATH=store-fixture:latest`

---

> **CI scope:** Only `apps/api/**` and `.github/workflows/api.yml` paths trigger CI.

## Files Added

| File | Purpose |
|---|---|
| `Dockerfile` | Multi-stage build; non-root runtime; uv dependency management |
| `.dockerignore` | Excludes test tooling, docs, and OS noise from the build context |
| `docs/deploy.md` | This document |
