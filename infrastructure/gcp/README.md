# Google Cloud foundation

Day-0 layout for issue #5. One small project, `us-central1`, always-free resource shapes. ADR [0004](../../docs/adr/0004-keep-the-cloud-foundation-on-free-tier.md) is the decision.

The local API does not read these resources. It still serves the committed fixture and starts without GCP credentials.

## Project

| | |
| --- | --- |
| Project | `retailtwin-ai-511002` |
| Region | `us-central1` |
| Operator account | the Google account that owns this project |
| Other RetailTwin project | `retailtwin-ai` has billing disabled. Do not enable APIs there. |
| Out of bounds | `cn-prj-17cd4` (Mindful Vibes) and `ess-prj` |

Non-secret variables are in the repository root [`.env.example`](../../.env.example). Copy it to `.env` only for local overrides. Do not commit `.env` or a service-account JSON key.

## What is created

| Resource | Day-0 shape | Always-free limit |
| --- | --- | --- |
| Firestore `(default)` | Standard, Native, `us-central1`, delete protection, no PITR, no documents | 1 GiB, 50,000 reads, 20,000 writes, 20,000 deletes per day, 10 GiB egress per month. One database. |
| Pub/Sub `store-events` | Topic only. Storage allowed in `us-central1` only. No subscription. | 10 GiB of messages per month |
| BigQuery `retailtwin` | Empty dataset, on-demand, no reservation | 1 TiB of queries and 10 GiB of storage per month |
| Cloud Storage `retailtwin-ai-511002-assets` | Standard, private, uniform access, soft delete off | 5 GB-months in `us-central1`, `us-east1`, and `us-west1` combined |
| Artifact Registry `retailtwin` | Empty Docker repository | 0.5 GB per month |
| Cloud Run, Cloud Build, Secret Manager, Logging | APIs only | Cloud Run: 2 million requests, 360,000 GB-seconds, 180,000 vCPU-seconds, 1 GB North America egress. Cloud Build: 2,500 e2-standard-2 minutes. Secret Manager: 6 active versions and 10,000 accesses. Logging: 50 GiB ingested per project. |
| Vertex AI | API only. No model call. | Not on the always-free list |

[`required-apis.txt`](required-apis.txt) is the source of truth for the required APIs. Both bootstrap implementations enable all 14 APIs, and `verify.py` checks that the same 14 APIs are enabled.

These APIs stay off: Compute Engine, GKE, Cloud SQL, Memorystore, and Spanner. A VM is not part of this local setup, including the free `e2-micro`.

## Identities

No keys are created. Use Application Default Credentials for local admin commands.

| Account | May do | Must not receive |
| --- | --- | --- |
| `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com` | Firestore read/write, log write, publish to `store-events` | `roles/editor`, `roles/owner`, `roles/aiplatform.user` |
| `retailtwin-agent@retailtwin-ai-511002.iam.gserviceaccount.com` | Vertex AI user | `roles/datastore.user`, `roles/editor`, `roles/owner`, `roles/viewer` |

Issue #9 runs Cloud Run as `retailtwin-api`, in `us-central1`, with request-based billing and minimum instances at 0. The agent account is not that runtime account. Issue #2 is the first change that may call a model.

## Budget alert

Expected net spend is 0 USD while usage stays inside the table above. Free-tier credits are included, so normal free usage does not count as spend.

The intended alert is a monthly budget named `retailtwin-dev-guard` for 25,000 VND on this project only, at 50%, 90%, and 100% of actual spend. The billing account currency determines whether that amount is accepted. The alert does not disable billing.

Budget presence and an operator's permission to view it are runtime states. `verify.sh` / `verify.py` report exit code 2 when the foundation checks pass but the alert is absent or cannot be confirmed; a billing administrator can create it using [AUTHENTICATION.md](AUTHENTICATION.md).

## Apply and check

```bash
# Unix / macOS: requires the Unix `gcloud` and `bq` executables on PATH.
CONFIRM_GCP_BOOTSTRAP=yes infrastructure/gcp/bootstrap.sh
infrastructure/gcp/verify.sh

# Windows: use the Python scripts, which invoke gcloud.cmd and bq.cmd.
set CONFIRM_GCP_BOOTSTRAP=yes
python infrastructure/gcp/bootstrap.py
python infrastructure/gcp/verify.py
```

`bootstrap.sh` is the Unix/macOS implementation; `bootstrap.py` is the Windows implementation. Both are idempotent and accept only `retailtwin-ai-511002`. They refuse every other project id before calling `gcloud`, reject a project with billing disabled, and reject regions other than `us-central1`. They bind roles only on `retailtwin-api` and `retailtwin-agent`, and do not create keys, documents, subscriptions, secrets, Cloud Run services, or Vertex calls.

`verify.sh` / `verify.py` exit 0 when the foundation and budget both match, 2 when only the budget is not confirmed, and 1 for another mismatch. Windows users should run `verify.py`; it invokes `gcloud.cmd` directly.

## Later issues

- #6 writes documents into `(default)`. It does not create another database.
- #7 adds the subscription and BigQuery tables.
- #2 makes the Gemini read-tool call.
- #9 deploys the scale-to-zero Cloud Run service.
- Foundation gate #10 stays open until those exist.
