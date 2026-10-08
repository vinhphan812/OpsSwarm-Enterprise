# 0004. Keep the cloud foundation on the free tier

Date: 2026-10-08

## Status

Accepted

## Context

Issue #5 needs one shared Google Cloud project, a region, service identities, and a cost guard before Firestore, Pub/Sub, Gemini, or Cloud Run work can start. The local application does not need a large or multi-region deployment.

Three existing projects were considered. `retailtwin-ai` has billing disabled, so the required APIs cannot be turned on. `cn-prj-17cd4` (Mindful Vibes) is a different product. `ess-prj` is not accessible to the operator account. `retailtwin-ai-511002` is active, owned by the operator account, and already has billing linked. This identity can read that link and cannot administer the billing account, so it cannot create the budget alert itself.

The always-free limits that matter here are regional. Cloud Storage's free 5 GB applies in `us-central1`, `us-east1`, and `us-west1`. Firestore's free daily allowance applies to one database per project. Vertex AI is not on the always-free list: enabling its API is free, and model calls are not. A second Firestore database, a multi-region database, Enterprise edition, point-in-time recovery, backups, a Compute Engine VM, and a Cloud Run service with minimum instances would leave that shape.

One shared service account was set aside. The API must be able to write the Live Twin later. The Vertex caller must not. `docs/ARCHITECTURE.md` already says Gemini does not receive database credentials and does not write live state.

## Decision

Use project `retailtwin-ai-511002` in `us-central1` as the only RetailTwin cloud project. Keep day-0 resources inside the always-free shapes:

- Firestore `(default)` is Standard edition, Native mode, in `us-central1`, with delete protection and without point-in-time recovery. Do not create a second database.
- Pub/Sub topic `store-events` stores messages only in `us-central1`.
- BigQuery dataset `retailtwin` is in `us-central1` and stays on-demand. Do not buy a reservation.
- Cloud Storage bucket `retailtwin-ai-511002-assets` is Standard, private, and in `us-central1`.
- Artifact Registry docker repository `retailtwin` is in `us-central1`.
- Cloud Run, Cloud Build, Secret Manager, and Vertex AI APIs are enabled. No service, trigger, secret version, endpoint, or model call is created.
- Compute Engine, GKE, Cloud SQL, Memorystore, and Spanner stay disabled.

Use two runtime identities and do not create keys:

- `retailtwin-api` may write Firestore, write logs, and publish to `store-events`.
- `retailtwin-agent` may call Vertex AI only. It must not receive `roles/datastore.user`, `roles/editor`, `roles/owner`, or `roles/viewer`.

The cost alert is a monthly budget named `retailtwin-dev-guard` for 25,000 VND of net spend on this project, at 50%, 90%, and 100%. That is about 1 USD. The billing account currency is VND, so a USD amount is rejected. This decision does not disable billing automatically.

Non-secret variables live in the repository root `.env.example`, which is the file the app and the README already use.

## Consequences

- Issue #6 seeds the existing `(default)` database. A second database would sit outside the one free database.
- Issue #7 publishes to `store-events` and writes the `retailtwin` dataset. It does not add a subscription or a table in this decision.
- Issue #2 is the first change allowed to call Vertex AI. Those calls are the spend that the 25,000 VND alert is there to catch.
- Issue #9 deploys Cloud Run in `us-central1` with request-based billing, minimum instances at 0, and runtime service account `retailtwin-api`. The agent identity is not that runtime account.
- The operator account remains a project owner. Owner is broader than either runtime identity. Day-0 code uses the service accounts, not a downloaded key.
- `bootstrap.sh` and `verify.sh` accept only `retailtwin-ai-511002`. Any other project id stops the script before `gcloud` runs. The scripts grant roles only to `retailtwin-api` and `retailtwin-agent`.
- The local API still reads the committed fixture and still starts without GCP credentials.
- Foundation gate #10 stays open. This record does not seed data, call Gemini, or deploy a service.
- A billing administrator created the budget. The operator account can see that billing is linked and cannot list budgets.
- Pull request:
- Issue: https://github.com/vinhphan812/retailtwin-ai/issues/5
- Supersedes:
- Superseded by:
