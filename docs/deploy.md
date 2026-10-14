# Day-0 API on Cloud Run

Issue [#9](https://github.com/vinhphan812/retailtwin-ai/issues/9).

The container serves the committed store fixture. It does not call Vertex AI and it does not read Firestore as the Live Twin. No credential file is copied into the image. `.dockerignore` excludes `.env` and `.env.*`.

ADR 0004 fixes the shape: project `retailtwin-ai-511002`, region `us-central1`, Artifact Registry repository `retailtwin`, minimum instances `0`, runtime account `retailtwin-api`. Do not create `retailtwin-runtime`. The fixture path is inside the image, so the deploy does not use Secret Manager.

## Deploy

Docker Desktop must be running. The machine account needs permission to push to Artifact Registry and to deploy Cloud Run as `retailtwin-api`.

```bash
scripts/deploy-cloudrun.sh
```

The script builds `linux/amd64` (Cloud Run rejects an arm64 image with `exec format error`), pushes:

`us-central1-docker.pkg.dev/retailtwin-ai-511002/retailtwin/retailtwin-api:<git-sha>`

and deploys `retailtwin-api` with:

- service account `retailtwin-api@retailtwin-ai-511002.iam.gserviceaccount.com`
- public invoker (`--allow-unauthenticated`), so `curl` can call `/health` and `/store`
- port `8080`
- minimum instances `0`, maximum instances `2`
- `APP_ENV=production`
- `CORS_ORIGINS` for the Firebase Hosting hosts and local Vite (`http://localhost:5173`, `http://127.0.0.1:5173`)

Uvicorn does not read `PORT` by itself. The image entrypoint binds `0.0.0.0:${PORT:-8080}`.

Skip the HTTP check with `VERIFY=false scripts/deploy-cloudrun.sh`.

## Check

```bash
curl -sS https://retailtwin-api-5rgtvr4gpa-uc.a.run.app/health
curl -sS https://retailtwin-api-5rgtvr4gpa-uc.a.run.app/ready
curl -sS https://retailtwin-api-5rgtvr4gpa-uc.a.run.app/store
```

`/health` returns `fixture_loaded: true` and `app_env: production`. `/ready` returns `ready: true`. `/store` returns `store-001` and `P001`.

A clean `linux/amd64` deploy on 2026-10-13 produced revision `retailtwin-api-00005-5ps`, serving 100 percent of traffic. Logs for a revision are in Cloud Logging under `cloud_run_revision`.

## Rollback

```bash
gcloud run revisions list --service retailtwin-api --region us-central1 --project retailtwin-ai-511002

gcloud run services update-traffic retailtwin-api \
  --to-revisions PREVIOUS_REVISION=100 \
  --region us-central1 \
  --project retailtwin-ai-511002
```

## Out of scope

- Firebase Hosting for the web app
- A GitHub Actions deploy job
- Vertex AI and the Firestore Live Twin on this service
