# Production frontend deployment

The production web app is a static Vite build hosted by Firebase Hosting:

- frontend: <https://retailtwin-ai-511002.web.app>
- API: <https://retailtwin-api-537192856637.us-central1.run.app>
- Firebase/GCP project: `retailtwin-ai-511002`

The API URL is public configuration, not a secret. Vite embeds it in the JavaScript bundle at build time. Do not commit `.env` files, Firebase tokens, service-account keys, or downloaded credentials.

## Prerequisites

- Node.js `>=20.17` and npm
- `firebase-tools`
- a short-lived authenticated Firebase CLI session authorised to deploy Hosting in `retailtwin-ai-511002`
- the Cloud Run API configured to allow both production Hosting origins:
  - `https://retailtwin-ai-511002.web.app`
  - `https://retailtwin-ai-511002.firebaseapp.com`

The project has `.firebaserc` and `firebase.json` checked in. Hosting serves `apps/web/dist`, applies immutable caching only to hashed assets, does not cache `index.html`, and rewrites browser routes to the SPA entry point.

## Deploy

Run from the repository root:

```bash
./scripts/deploy-web.sh
```

The script runs a clean dependency install and production build with the exact Cloud Run origin. It refuses deployment if the bundle contains a localhost origin or does not contain the expected API origin, then deploys only the named Hosting site.

For a manual build inspection without deploying:

```bash
cd apps/web
npm ci
VITE_API_BASE_URL=https://retailtwin-api-537192856637.us-central1.run.app npm run build
grep -R -F 'https://retailtwin-api-537192856637.us-central1.run.app' dist
```

## API CORS

Cloud Run reads the API allow-list from `CORS_ORIGINS`. Production uses the two deterministic Firebase origins:

```bash
# cors-env.yaml (temporary local file; do not commit)
cat > cors-env.yaml <<'YAML'
CORS_ORIGINS: "https://retailtwin-ai-511002.web.app,https://retailtwin-ai-511002.firebaseapp.com"
YAML

gcloud run services update retailtwin-api \
  --project retailtwin-ai-511002 \
  --region us-central1 \
  --env-vars-file cors-env.yaml
rm cors-env.yaml
```

Do not use `*`. Updating this variable creates a new revision of the existing service without changing its image.

## Verify

```bash
FRONTEND_ORIGIN=https://retailtwin-ai-511002.web.app
API_ORIGIN=https://retailtwin-api-537192856637.us-central1.run.app

curl --fail --show-error --silent --head "${FRONTEND_ORIGIN}/"
curl --fail --show-error --silent "${API_ORIGIN}/health"
curl --fail --show-error --silent "${API_ORIGIN}/store"

curl --fail --show-error --silent --dump-header - --output /dev/null \
  --header "Origin: ${FRONTEND_ORIGIN}" \
  "${API_ORIGIN}/health"
curl --fail --show-error --silent --dump-header - --output /dev/null \
  --header "Origin: ${FRONTEND_ORIGIN}" \
  "${API_ORIGIN}/store"
```

Both API responses must include:

```text
access-control-allow-origin: https://retailtwin-ai-511002.web.app
```

Finally, open the frontend in a clean browser profile. Confirm the app shell and 3D store render, and confirm `/health` and `/store` succeed in the browser network panel with no CORS error.

## Roll back

List Hosting releases and clone a known-good version into a new release:

```bash
firebase hosting:releases:list --site retailtwin-ai-511002 --project retailtwin-ai-511002
firebase hosting:clone \
  retailtwin-ai-511002:<SOURCE_VERSION> \
  retailtwin-ai-511002:live \
  --project retailtwin-ai-511002
```

If the CORS revision causes a regression, list revisions and route traffic back:

```bash
gcloud run revisions list \
  --service retailtwin-api \
  --region us-central1 \
  --project retailtwin-ai-511002

gcloud run services update-traffic retailtwin-api \
  --to-revisions <KNOWN_GOOD_REVISION>=100 \
  --region us-central1 \
  --project retailtwin-ai-511002
```
