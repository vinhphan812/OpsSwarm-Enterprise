# Production frontend deployment

The production web app is a static Vite build hosted by Firebase Hosting:

- frontend: <https://retailtwin-ai-511002.web.app>
- API: <https://retailtwin-api-537192856637.us-central1.run.app>
- Firebase/GCP project: `retailtwin-ai-511002`

The API URL is public configuration, not a secret. Vite embeds it in the JavaScript bundle at build time. Do not commit `.env` files, Firebase tokens, service-account keys, or downloaded credentials.

## Automated CD Pipeline (GitHub Actions)

Production deployment is fully automated via GitHub Actions (see `.github/workflows/web.yml`):

1. **Trigger**: Automatically on push to `main` when web app files change
2. **Build & Test**: Runs TypeScript compilation, production build, and test suite
3. **Security Checks**:
   - Rejects `localhost` or `127.0.0.1` in production bundle
   - Verifies expected API origin is embedded
   - Rejects unexpected API origins
4. **Deploy**: Uses WIF/OIDC authentication to Firebase Hosting (no secrets required)
5. **Smoke Verification**: Post-deploy checks:
   - Index page loads
   - SPA rewrite works (`/twin` → `index.html`)
   - JS/CSS assets load
   - Production API origin embedded in bundle
   - No localhost origins in deployed assets
   - CORS permits frontend origin
   - API health endpoint returns OK

### Repository Variables Required

Configure these in GitHub repository Settings → Variables:

| Variable | Value | Description |
|----------|-------|-------------|
| `FIREBASE_API_BASE_URL` | `https://retailtwin-api-537192856637.us-central1.run.app` | Production API origin |
| `FIREBASE_SITE_ID` | `retailtwin-ai-511002` | Firebase Hosting site ID |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | (GCP WIF provider ID) | OIDC provider for WIF auth |

### Repository Secrets Required

Configure in GitHub repository Settings → Secrets:

| Secret | Description |
|--------|-------------|
| `GCP_DEPLOY_SA` | Service account for deployment (`github-actions@retailtwin-ai-511002.iam.gserviceaccount.com`) with Firebase Hosting Admin role |

## Manual Deployment (Emergency Only)

For emergency manual deployment, use the deploy script:

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

## Roll Back

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
