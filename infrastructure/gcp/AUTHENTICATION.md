# GCP authentication guide

## Local development

Local commands use Application Default Credentials (ADC) provided by the Google Cloud CLI. The foundation scripts do not create service-account JSON keys.

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project retailtwin-ai-511002
```

Confirm the active account and project without recording the account identifier in repository files:

```bash
gcloud auth list
gcloud config get-value account
gcloud config get-value project
```

Run the platform-appropriate read-only verification command from [README.md](README.md). Exit code `0` means the current invocation confirmed the foundation and budget; `2` means the foundation checks passed but the budget is absent or could not be confirmed; `1` indicates another verification failure.

## Runtime identities

The foundation creates two runtime service accounts without user-managed keys:

| Account | Purpose | Required role(s) | Must not receive |
| --- | --- | --- | --- |
| `retailtwin-api@...` | API runtime | `roles/datastore.user`, `roles/logging.logWriter`, and topic-level `roles/pubsub.publisher` | `roles/editor`, `roles/owner`, `roles/aiplatform.user` |
| `retailtwin-agent@...` | Agent runtime | `roles/aiplatform.user` | `roles/datastore.user`, `roles/editor`, `roles/owner`, `roles/viewer`, `roles/pubsub.publisher`, `roles/pubsub.admin` |

The API runtime account must not receive Vertex AI access. The agent runtime account requires `roles/aiplatform.user`; it must not receive Firestore or Pub/Sub publishing access. These constraints match the checks in `verify.sh` and `verify.py`.

## CI/CD

The repository does not currently contain a configured GitHub Actions deployment identity or Workload Identity Federation provider. Do not infer that one exists from the local bootstrap scripts. A future deployment change must document its dedicated identity, federation provider, least-privilege roles, and GitHub configuration without committing credentials.

## Local API without GCP

The local API starts with a committed fixture and does not require GCP credentials. Configure real GCP or Gemini integration only through the appropriate future application/deployment work; do not commit `.env` files, API keys, access tokens, or service-account keys.

## Troubleshooting

### `google.auth.default` fails

```bash
gcloud auth application-default login
gcloud auth list
```

### Permission denied on GCP resources

Confirm the intended project, then request the minimum required role from the project administrator:

```bash
gcloud config get-value project
gcloud config set project retailtwin-ai-511002
```

### Budget alert cannot be confirmed

The `retailtwin-dev-guard` monthly budget can require a billing administrator. An authorized administrator can create it with:

```bash
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --billing-project=retailtwin-ai-511002 \
  --display-name=retailtwin-dev-guard \
  --budget-amount=25000VND \
  --calendar-period=month \
  --filter-projects=projects/retailtwin-ai-511002 \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0
```

A budget alert does not disable billing.
