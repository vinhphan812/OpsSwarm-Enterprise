# Cloud Runtime Matrix

Canonical production GCP/Firebase configuration. Issue [#134](https://github.com/vinhphan812/retailtwin-ai/issues/134).

## Overview

This document freezes the single source of truth for every cloud resource that the RetailTwin AI project uses or plans to use. Terraform issue [#99](https://github.com/vinhphan812/retailtwin-ai/issues/99) owns provisioning; this document owns the shape and identity of every resource that Terraform will create.

The matrix is read-only verification, not provisioning. All values are non-secret identifiers unless the column says otherwise.

---

## Canonical Identity Table

| Service / Resource | Exact Resource Name / ID | Region / Location | Owning Issue | Runtime Identity | Minimum IAM Roles | Environment Variables | Secret References | Terraform #99 | Verification Command |
|---|---|---|---|---|---|---|---|---|---|
| **GCP Project** | `retailtwin-ai-511002` | — | [#5](https://github.com/vinhphan812/retailtwin-ai/issues/5) | — | — | `GCP_PROJECT_ID` | — | owns | `gcloud projects describe retailtwin-ai-511002` |
| **Artifact Registry Repository** | `us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin` | `us-central1` | [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9) | CI/CD / operator | `roles/artifactregistry.writer` | `ARTIFACT_REGISTRY_LOCATION`, `ARTIFACT_REGISTRY_REPO` | — | owns | `gcloud artifacts repositories describe retailtwin --location=us-central1 --project=retailtwin-ai-511002 --format='value(format)'` |
| **Cloud Run Service** | `retailtwin-api` | `us-central1` | [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9) | `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | `roles/run.admin`, `roles/iam.serviceAccountUser` (for SA) | `APP_ENV`, `LOG_LEVEL`, `CORS_ORIGINS`, `GCP_PROJECT_ID`, `GCP_REGION` | — | owns | `gcloud run services describe retailtwin-api --region=us-central1 --project=retailtwin-ai-511002 --format='value(status.url)'` |
| **Cloud Build** | (project-level) | `us-central1` | [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9) | operator / CI/CD | `roles/cloudbuild.builds.editor` | — | — | owns | `gcloud builds list --project=retailtwin-ai-511002` |
| **GitHub Actions WIF** | Workload Identity Provider (value in `GCP_WORKLOAD_IDENTITY_PROVIDER` repo variable) | — | [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9) | `github-actions@retailtwin-ai-511002.iam.gserviceaccount.com` | `roles/run.admin`, `roles/artifactregistry.writer`, `roles/secretmanager.secretAccessor` | — | — | partial | `gcloud iam workload-identity-pools providers describe <provider-name> --location=global --project=retailtwin-ai-511002` |
| **Firestore Database** | `(default)` | `us-central1` | [#6](https://github.com/vinhphan812/retailtwin-ai/issues/6) | `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | `roles/datastore.user` | `FIRESTORE_DATABASE` | — | owns | `gcloud firestore databases describe --database=(default) --project=retailtwin-ai-511002` |
| **Firestore Claim Collection** | `store_event_claims/{event_id}` in `(default)` | `us-central1` | [#7](https://github.com/vinhphan812/retailtwin-ai/issues/7) | `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | (inherited from Firestore) | — | — | owns | `gcloud firestore collections describe store_event_claims --database=(default) --project=retailtwin-ai-511002` |
| **Pub/Sub Topic** | `store-events` | `us-central1` (storage constraint) | [#7](https://github.com/vinhphan812/retailtwin-ai/issues/7) | `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | topic-level `roles/pubsub.publisher` | `STORE_EVENTS_TOPIC` | — | owns | `gcloud pubsub topics describe store-events --project=retailtwin-ai-511002` |
| **Pub/Sub Subscription** | `store-events-analytics` | `us-central1` | [#7](https://github.com/vinhphan812/retailtwin-ai/issues/7) | (pull consumer) | `roles/pubsub.subscriber` | `STORE_EVENTS_SUBSCRIPTION` | — | owns | `gcloud pubsub subscriptions describe store-events-analytics --project=retailtwin-ai-511002` |
| **BigQuery Dataset** | `retailtwin` | `us-central1` | [#7](https://github.com/vinhphan812/retailtwin-ai/issues/7) | (operator / CI/CD lander) | `roles/bigquery.dataEditor` (for lander) | `BIGQUERY_DATASET`, `BIGQUERY_LOCATION` | — | owns | `bq show --project_id=retailtwin-ai-511002 retailtwin` |
| **BigQuery Table** | `retailtwin.sales_events` | `us-central1` | [#7](https://github.com/vinhphan812/retailtwin-ai/issues/7) | (see dataset) | (see dataset) | — | — | owns | `bq show --project_id=retailtwin-ai-511002 retailtwin.sales_events` |
| **BigQuery Table** | `retailtwin.inventory_events` | `us-central1` | [#7](https://github.com/vinhphan812/retailtwin-ai/issues/7) | (see dataset) | (see dataset) | — | — | owns | `bq show --project_id=retailtwin-ai-511002 retailtwin.inventory_events` |
| **BigQuery Table** | `retailtwin.agent_actions` | `us-central1` | [#7](https://github.com/vinhphan812/retailtwin-ai/issues/7) | (see dataset) | (see dataset) | — | — | owns | `bq show --project_id=retailtwin-ai-511002 retailtwin.agent_actions` |
| **BigQuery Table** | `retailtwin.agent_action_audit` | `us-central1` | [#35](https://github.com/vinhphan812/retailtwin-ai/issues/35) | (operator / audit writer) | `roles/bigquery.dataEditor` | — | — | owns | `bq show --project_id=retailtwin-ai-511002 retailtwin.agent_action_audit` |
| **Vertex AI API** | `aiplatform.googleapis.com` | `us-central1` | [#2](https://github.com/vinhphan812/retailtwin-ai/issues/2), [#134](https://github.com/vinhphan812/retailtwin-ai/issues/134) | `retailtwin-agent@retailtwin-ai-511002.iam.gserviceaccount.com` | `roles/aiplatform.user` | `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | — | owns | `gcloud ai models list --region=us-central1 --project=retailtwin-ai-511002` |
| **Vertex AI Model** | `gemini-2.5-flash` (canonical) | `us-central1` | [#2](https://github.com/vinhphan812/retailtwin-ai/issues/2) | (see Vertex AI API) | (see Vertex AI API) | `LLM_PROVIDER=vertex_gemini`, `LLM_MODEL=gemini-2.5-flash` | — | owns | `gcloud ai models describe gemini-2.5-flash --region=us-central1 --project=retailtwin-ai-511002` |
| **Cloud Storage Bucket** | `gs://retailtwin-ai-511002-assets` | `us-central1` | [#5](https://github.com/vinhphan812/retailtwin-ai/issues/5) | (operator) | `roles/storage.objectViewer` (for read) | `GCS_BUCKET` | — | owns | `gcloud storage buckets describe gs://retailtwin-ai-511002-assets --project=retailtwin-ai-511002` |
| **Secret Manager** | (project-level) | — | [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9), [#134](https://github.com/vinhphan812/retailtwin-ai/issues/134) | `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` (future) | `roles/secretmanager.secretAccessor` (future) | — | Future: `STORE_FIXTURE_PATH`, `LLM_API_KEY` (never) | owns | `gcloud secrets list --project=retailtwin-ai-511002` |
| **Firebase Hosting** | `retailtwin-ai-511002` | (global) | [#43](https://github.com/vinhphan812/retailtwin-ai/issues/43), [#132](https://github.com/vinhphan812/retailtwin-ai/issues/132) | Firebase project | `roles/firebase.hosting.Admin` (CI/CD) | `VITE_API_BASE_URL` | — | not owned | `firebase hosting:channel:list --project=retailtwin-ai-511002` |
| **CORS Allow-list** | Cloud Run `CORS_ORIGINS` env var | — | [#43](https://github.com/vinhphan812/retailtwin-ai/issues/43), [#134](https://github.com/vinhphan812/retailtwin-ai/issues/134) | Cloud Run runtime | — | `CORS_ORIGINS` | — | not owned | See verification script |

---

## Service Account Canonical Names

The project uses **two runtime service accounts** and **one CI/CD service account**:

| Account | Email | Purpose | Owned By | Workflow Secret |
|---|---|---|---|---|
| `retailtwin-api` | `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | Cloud Run API runtime | [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9) | `GCP_RUNTIME_SA` |
| `retailtwin-agent` | `retailtwin-agent@retailtwin-ai-511002.iam.gserviceaccount.com` | Vertex AI / agent inference | [#2](https://github.com/vinhphan812/retailtwin-ai/issues/2) | — |
| `github-actions` | `github-actions@retailtwin-ai-511002.iam.gserviceaccount.com` | GitHub Actions CI/CD | [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9) | `GCP_DEPLOY_SA` |

> **Note**: The GitHub Actions workflow (`api.yml`) currently uses `secrets.GCP_RUNTIME_SA` to specify the Cloud Run runtime service account, not a hardcoded email. The secret value should be `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com`.

> **Note on `retailtwin-runtime`**: The workflow previously referenced `retailtwin-runtime@retailtwin-ai-511002.iam.gserviceaccount.com` in a draft configuration. This account **does not exist** and was never provisioned. The canonical runtime SA is `retailtwin-api`.

---

## Container Registry Current State

> **Migration in progress**: The GitHub Actions workflow (`api.yml`) currently uses `gcr.io`. Artifact Registry is the **target canonical registry**. Migration tracked in issue #134.

| | Current (in use) | Target Canonical |
|---|---|---|
| Registry | `gcr.io` | `us-central1-docker.pkg.dev` |
| Repository | `retailtwin-ai-511002` | `retailtwin-ai-511002/retailtwin` |
| Image | `retailtwin-api` | `retailtwin-api` |
| Full current path | `gcr.io/retailtwin-ai-511002/retailtwin-api:<tag>` | — |
| Full target path | — | `us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api:<tag>` |

Terraform #99 will own the migration to Artifact Registry.

---

## Secret Manager Canonical State

As of 2026-10-15, **Secret Manager has no secrets provisioned**. The foundation (`bootstrap.sh` / `bootstrap.py`) creates zero secrets. The deploy script (`deploy-cloudrun.sh`) uses the committed fixture path inside the container image and does not read Secret Manager.

Future secrets planned:

| Secret Name | Purpose | Referenced By | Status |
|---|---|---|---|
| `store-fixture` | Production store fixture path | Cloud Run `STORE_FIXTURE_PATH` | Future (#134) |

> **Note**: The GitHub Actions workflow had a commented `--secrets` line referencing `STORE_FIXTURE_PATH=store-fixture:latest`. This was a forward reference. The day-0 deploy does not use Secret Manager. Terraform #99 will own the future provisioning.

---

## GitHub Actions Workload Identity Federation

The `api.yml` workflow uses Workload Identity Federation (WIF) for production deployment. Current workflow references:

### Current Repository Variables and Secrets (from `api.yml`)

| Variable/Secret | Source in Workflow | Value |
|---|---|---|
| `vars.GCP_WORKLOAD_IDENTITY_PROVIDER` | Workflow uses `vars.GCP_WORKLOAD_IDENTITY_PROVIDER` | Full resource name of the WIF provider |
| `secrets.GCP_DEPLOY_SA` | Workflow uses `secrets.GCP_DEPLOY_SA` | CI/CD service account for docker/auth |
| `secrets.GCP_RUNTIME_SA` | Workflow uses `secrets.GCP_RUNTIME_SA` | Cloud Run runtime service account |

> **Note**: The workflow does not currently use `GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT`. The actual variable names are `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SA`, and `GCP_RUNTIME_SA`.

### Minimum Roles for CI/CD Service Account

| Role | Purpose |
|---|---|
| `roles/run.admin` | Deploy Cloud Run services |
| `roles/artifactregistry.writer` | Push container images (gcr.io currently; migration to Artifact Registry planned) |
| `roles/iam.workloadIdentityUser` | WIF impersonation |

### WIF Provider Configuration (Terraform #99 owns this)

```bash
# Terraform #99 will provision:
# - WorkloadIdentityPool: retailtwin-ai-pool
# - WorkloadIdentityProvider: github-actions-provider (attribute mapping)
# - ServiceAccount: github-actions@retailtwin-ai-511002.iam.gserviceaccount.com
# - SA IAM bindings for above roles
```

---

## Required GCP APIs

The 14 foundation APIs (from `infrastructure/gcp/required-apis.txt`):

| API | Purpose | Terraform #99 |
|---|---|---|
| `aiplatform.googleapis.com` | Vertex AI | owns |
| `run.googleapis.com` | Cloud Run | owns |
| `cloudbuild.googleapis.com` | Cloud Build | owns |
| `artifactregistry.googleapis.com` | Artifact Registry | owns |
| `firestore.googleapis.com` | Firestore | owns |
| `bigquery.googleapis.com` | BigQuery | owns |
| `pubsub.googleapis.com` | Pub/Sub | owns |
| `storage.googleapis.com` | Cloud Storage | owns |
| `secretmanager.googleapis.com` | Secret Manager | owns |
| `logging.googleapis.com` | Cloud Logging | owns |
| `cloudbilling.googleapis.com` | Billing | owns |
| `billingbudgets.googleapis.com` | Budget alerts | owns |
| `cloudresourcemanager.googleapis.com` | Resource Manager | owns |
| `iam.googleapis.com` | Identity and Access Management | owns |

---

## Firebase Hosting Canonical Configuration

| Setting | Value |
|---|---|
| Firebase project | `retailtwin-ai-511002` |
| Hosting site ID | `retailtwin-ai-511002` |
| Public directory | `apps/web/dist` |
| Frontend URL | `https://retailtwin-ai-511002.web.app` |
| Frontend URL (alt) | `https://retailtwin-ai-511002.firebaseapp.com` |

Firebase is **not owned by Terraform #99**. It is managed by `firebase-tools` and `.firebaserc` / `firebase.json`.

---

## Production CORS Allow-list

Cloud Run reads `CORS_ORIGINS` from the environment. The canonical production origins are:

| Origin | Purpose |
|---|---|
| `https://retailtwin-ai-511002.web.app` | Firebase Hosting primary |
| `https://retailtwin-ai-511002.firebaseapp.com` | Firebase Hosting alternate |
| `http://localhost:5173` | Local Vite dev |
| `http://127.0.0.1:5173` | Local Vite dev (alternate) |

The value is set in Cloud Run via `deploy-cloudrun.sh` or a manual `gcloud run services update` with `--env-vars-file`.

---

## Terraform #99 Relationship

Issue [#99](https://github.com/vinhphan812/retailtwin-ai/issues/99) owns **all provisioning** of the resources listed in this document. This matrix is the specification that Terraform #99 must implement.

> **Note on current state**: Resources listed here represent the **observed production state** as of October 2026. The current runtime contract is verified by `scripts/verify-cloud-preflight.sh`. Terraform #99 will codify and potentially migrate these resources.

| Resource Category | Current State | Terraform #99 Scope |
|---|---|---|
| Project, APIs, IAM | **Already provisioned** | Codify existing |
| Service accounts | **Already provisioned** | Import/adopt, no recreation |
| Firestore, Pub/Sub, BigQuery, Cloud Storage | **Already provisioned** | Import/adopt |
| Artifact Registry repository | **Target only** | Must create |
| Cloud Run service | **Already deployed** | Import/adopt |
| Secret Manager secrets | **Empty (day-0)** | Create when needed |
| WIF pool and provider | **Already configured** | Import/adopt |
| Firebase Hosting | **Already configured** | **Not owned** (firebase-tools) |
| CORS environment variable | **Runtime config** | **Not owned** |

---

## Reconciled Conflicts Summary

| Conflict | Resolution |
|---|---|
| `.env.example` missing `VERTEX_AI_LOCATION` | Added `VERTEX_AI_LOCATION=us-central1` |
| `AUTHENTICATION.md` says no WIF, workflow expects `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF is required for production deploy; AUTHENTICATION.md was stale. Document WIF as required. |
| Foundation docs use `retailtwin-api@` / `retailtwin-agent@` vs workflow uses `retailtwin-runtime@` | `retailtwin-runtime` does not exist. Canonical is `retailtwin-api`. Workflow reference removed. |
| Docs alternate between Artifact Registry and `gcr.io` | Artifact Registry (`us-central1-docker.pkg.dev`) is canonical. `gcr.io` references removed. |
| Secret Manager described as active but workflow has commented secrets | Secret Manager is empty. The commented line was a forward reference. Day-0 does not use Secret Manager. |
| Firebase Hosting CORS not in foundation verifier | CORS is runtime configuration, not foundation. Added to preflight verifier. |

---

## Verification

Run the preflight verifier:

```bash
./scripts/verify-cloud-preflight.sh
```

This script is read-only and prints no secret values. See [scripts/verify-cloud-preflight.sh](../scripts/verify-cloud-preflight.sh).
