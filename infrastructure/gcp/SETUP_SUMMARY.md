# GCP setup validation summary

## What this repository can validate

The GCP foundation scripts are designed to be reproducible and non-destructive outside an explicit bootstrap run:

- `bootstrap.sh` is the Unix/macOS bootstrap path and uses `gcloud` and `bq` from `PATH`.
- `bootstrap.py` is the Windows bootstrap path and uses `gcloud.cmd` and `bq.cmd`.
- `verify.sh` and `verify.py` are read-only verification paths. They check the resources and API manifest described in [README.md](README.md).
- Both bootstrap implementations guard the canonical project and region, and do not create service-account keys, Firestore documents, Pub/Sub subscriptions, Secret Manager versions, Cloud Run services, or Vertex calls.

Run the appropriate commands from [README.md](README.md) after authenticating with an account authorized for the intended project. Script success or failure is evidence only for that invocation; it is not a statement about another operator's local environment.

## Local and provisioned state is not tracked

This repository does not establish or retain any individual operator's:

- untracked `.env` contents;
- `gcloud` or Application Default Credential login state;
- project IAM, billing, or budget permissions;
- provisioned resource state; or
- budget-alert existence.

Do not commit `.env`, service-account keys, access tokens, account identifiers, or verification output that includes personal details.

## Interpreting verification results

`verify.sh` and `verify.py` use these exit codes:

| Exit code | Meaning |
| --- | --- |
| 0 | The checks passed, including confirmation of the budget alert, for the current authenticated invocation. |
| 2 | The foundation checks passed, but the budget alert could not be confirmed or is absent; a billing administrator may be required. |
| 1 | One or more foundation checks failed, the project guard rejected the invocation, or verification could not read a required resource. |

A billing administrator can create or confirm the `retailtwin-dev-guard` monthly budget according to the documented command in [AUTHENTICATION.md](AUTHENTICATION.md). Budget alerts do not disable billing.

## Follow-up work

- Issue #6 writes Firestore documents into the existing `(default)` database.
- Issue #7 adds the subscription and BigQuery tables.
- Issue #2 is the first change that may call a model.
- Issue #9 deploys the scale-to-zero Cloud Run service.
