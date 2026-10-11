#!/usr/bin/env python3
"""
Verify the day-0 Google Cloud foundation for RetailTwin AI.
Windows-compatible: calls gcloud.cmd and bq.cmd directly via subprocess.
Exit 0: foundation and budget match.
Exit 2: foundation matches but the budget alert is missing (needs billing admin).
Exit 1: something else does not match.
"""
import subprocess, json, sys, os, tempfile
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT  = os.environ.get("GCP_PROJECT_ID", "retailtwin-ai-511002")
REGION   = os.environ.get("GCP_REGION", "us-central1")
DATABASE = os.environ.get("FIRESTORE_DATABASE", "(default)")
TOPIC    = os.environ.get("STORE_EVENTS_TOPIC", "store-events")
DATASET  = os.environ.get("BIGQUERY_DATASET", "retailtwin")
BUCKET   = os.environ.get("GCS_BUCKET", "retailtwin-ai-511002-assets")
REPO     = os.environ.get("ARTIFACT_REGISTRY_REPO", "retailtwin")
BUDGET_NAME = "retailtwin-dev-guard"
API_SA   = f"retailtwin-api@{PROJECT}.iam.gserviceaccount.com"
AGENT_SA = f"retailtwin-agent@{PROJECT}.iam.gserviceaccount.com"
CANONICAL_PROJECT = "retailtwin-ai-511002"

GCLOUD = "gcloud.cmd"
BQ     = "bq.cmd"
BQ_REST = "https://bigquery.googleapis.com/bigquery/v2"
REQUIRED_APIS_FILE = Path(__file__).with_name("required-apis.txt")


def required_apis():
    """Read the shared required-GCP-API manifest."""
    try:
        return [
            line.strip()
            for line in REQUIRED_APIS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except OSError as exc:
        fail(f"Cannot read required API manifest {REQUIRED_APIS_FILE}: {exc}")
        return []

# ── Helpers ───────────────────────────────────────────────────────────────────
_failures = 0
_budget_blocked = 0

def _env():
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_CORE_PROJECT"] = PROJECT
    env["CLOUDSDK_BILLING_QUOTA_PROJECT"] = PROJECT
    return env

def run(*args, **kwargs):
    kwargs.setdefault("env", _env())
    kwargs.setdefault("text", True)
    kwargs.setdefault("capture_output", True)
    result = subprocess.run(list(args), **kwargs)
    return result.stdout.strip(), result.stderr.strip(), result.returncode

def bq_rest_get(path):
    """Call BigQuery REST API with gcloud auth token."""
    token_out, _, _ = run(GCLOUD, "auth", "print-access-token")
    token = token_out.strip()
    if not token:
        return None, "No access token"
    result = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Bearer {token}", f"{BQ_REST}{path}"],
        capture_output=True, text=True, env=_env()
    )
    try:
        return json.loads(result.stdout), result.stderr
    except Exception:
        return None, result.stdout or result.stderr

def pass_(msg):  print(f"PASS  {msg}")
def fail(msg):
    global _failures
    print(f"FAIL  {msg}", file=sys.stderr)
    _failures += 1
def note(msg):  print(f"NOTE  {msg}")

# ── Checks ─────────────────────────────────────────────────────────────────────
def main():
    global _budget_blocked

    print(f"Verifying {PROJECT} in {REGION}")

    if PROJECT != CANONICAL_PROJECT:
        fail(f"Refusing project {PROJECT}. Verification applies only to {CANONICAL_PROJECT}.")
        sys.exit(1)

    # Billing
    out, err, rc = run(GCLOUD, "billing", "projects", "describe", PROJECT,
                       "--format=value(billingEnabled)")
    if out == "True":
        pass_("Billing is enabled")
    else:
        fail(f"Billing is not enabled (got '{out}')")

    # Enabled APIs
    apis = required_apis()
    if not apis:
        sys.exit(1)
    out_list, err_list, _ = run(GCLOUD, "services", "list",
                                 "--enabled", "--project=" + PROJECT,
                                 "--format=value(config.name)")
    enabled = set(line.strip() for line in out_list.splitlines() if line.strip())
    for api in apis:
        if api in enabled:
            pass_(f"API {api}")
        else:
            fail(f"API {api} is not enabled")

    # Disabled APIs
    off = ["compute.googleapis.com", "container.googleapis.com",
           "sqladmin.googleapis.com", "redis.googleapis.com", "spanner.googleapis.com"]
    for api in off:
        if api not in enabled:
            pass_(f"API {api} stays off")
        else:
            fail(f"API {api} is enabled. This foundation does not use it.")

    # IAM policy
    pol_out, _, pol_rc = run(GCLOUD, "projects", "get-iam-policy",
                             PROJECT, "--format=json")
    try:
        pol = json.loads(pol_out)
    except Exception:
        pol = {}

    def get_roles(member_prefix):
        roles = set()
        for b in pol.get("bindings", []):
            if member_prefix in str(b.get("members", [])):
                roles.add(b.get("role", ""))
        return roles

    public_members = [m for b in pol.get("bindings", [])
                      for m in b.get("members", [])
                      if m in ("allUsers", "allAuthenticatedUsers")]
    if not public_members:
        pass_("Project IAM has no allUsers or allAuthenticatedUsers")
    else:
        fail(f"Project IAM has public members: {public_members}")

    api_roles = get_roles("serviceAccount:" + API_SA)
    agent_roles = get_roles("serviceAccount:" + AGENT_SA)

    def check(condition, msg):
        (pass_ if condition else fail)(msg)

    check(bool(api_roles), "retailtwin-api has project roles")
    check("roles/datastore.user" in api_roles, "retailtwin-api has roles/datastore.user")
    check("roles/logging.logWriter" in api_roles, "retailtstore-api has roles/logging.logWriter")
    check("roles/aiplatform.user" not in api_roles, "retailtwin-api does not have roles/aiplatform.user")
    check("roles/editor" not in api_roles and "roles/owner" not in api_roles,
          "retailtwin-api is not editor or owner")
    check(bool(agent_roles), "retailtwin-agent has project roles")
    check("roles/aiplatform.user" in agent_roles, "retailtwin-agent has roles/aiplatform.user")
    for forbidden in ["roles/datastore.user", "roles/datastore.owner",
                      "roles/editor", "roles/owner", "roles/viewer",
                      "roles/pubsub.publisher", "roles/pubsub.admin"]:
        check(forbidden not in agent_roles, f"retailtwin-agent does not have {forbidden}")

    # Service accounts
    for sa_email in [API_SA, AGENT_SA]:
        _, _, rc = run(GCLOUD, "iam", "service-accounts", "describe",
                       sa_email, "--project=" + PROJECT)
        if rc == 0:
            pass_(f"Service account {sa_email} exists")
        else:
            fail(f"Service account {sa_email} is missing")
        out_keys, _, _ = run(GCLOUD, "iam", "service-accounts", "keys", "list",
                             "--iam-account=" + sa_email, "--managed-by=user",
                             "--format=value(name)")
        key_count = len([l for l in out_keys.splitlines() if l.strip()])
        if key_count == 0:
            pass_(f"No user-managed key for {sa_email}")
        else:
            fail(f"User-managed key exists for {sa_email}")

    # Firestore
    db_out, _, db_rc = run(GCLOUD, "firestore", "databases", "list",
                            "--project=" + PROJECT, "--format=json")
    try:
        dbs = json.loads(db_out)
        if len(dbs) == 1:
            pass_("One Firestore database")
        else:
            fail(f"Expected one Firestore database, found {len(dbs)}")
    except Exception:
        fail("Firestore databases list did not respond")

    db_yaml, _, _ = run(GCLOUD, "firestore", "databases", "describe",
                        "--project=" + PROJECT, "--database=" + DATABASE, "--format=yaml")
    def yaml_has(text):
        return text.lower() in db_yaml.lower()
    checks = [
        ("locationId: us-central1", "Firestore location is us-central1"),
        ("type: firestore_native", "Firestore type is native"),
        ("databaseEdition: standard", "Firestore edition is standard"),
        ("freeTier: true", "Firestore free tier is on this database"),
        ("pointInTimeRecoveryEnablement: point_in_time_recovery_disabled", "Firestore PITR is off"),
        ("deleteProtectionState: delete_protection_enabled", "Firestore delete protection is on"),
    ]
    for yaml_snippet, msg in checks:
        check(yaml_has(yaml_snippet), msg)

    # Pub/Sub
    topic_out, _, topic_rc = run(GCLOUD, "pubsub", "topics", "describe",
                                 TOPIC, "--project=" + PROJECT, "--format=yaml")
    if topic_rc == 0:
        if "us-central1" in topic_out:
            pass_(f"Pub/Sub {TOPIC} stores messages only in us-central1")
        else:
            fail(f"Pub/Sub {TOPIC} storage regions are not us-central1")
    else:
        fail(f"Pub/Sub topic {TOPIC} did not respond")

    topic_pol_out, _, _ = run(GCLOUD, "pubsub", "topics", "get-iam-policy",
                               TOPIC, "--project=" + PROJECT, "--format=json")
    try:
        tpol = json.loads(topic_pol_out)
        publishers = set()
        for b in tpol.get("bindings", []):
            if b.get("role") == "roles/pubsub.publisher":
                publishers.update(b.get("members", []))
        allowed = {"serviceAccount:" + API_SA}
        if publishers == allowed:
            pass_(f"Topic {TOPIC} publishers are exactly {API_SA}")
        else:
            fail(f"Topic {TOPIC} publishers are not exactly {API_SA}: {publishers}")
    except Exception:
        fail("Could not read IAM for topic {TOPIC}")

    # BigQuery via REST API
    ds, ds_err = bq_rest_get(f"/projects/{PROJECT}/datasets/{DATASET}")
    if ds is not None:
        loc = ds.get("location", "").lower()
        if loc == "us-central1":
            pass_(f"BigQuery dataset {DATASET} is in us-central1")
        else:
            fail(f"BigQuery dataset location is '{ds.get('location')}'")
    else:
        fail(f"BigQuery dataset {DATASET} did not respond: {ds_err}")

    # Cloud Storage
    bucket_out, _, bucket_rc = run(GCLOUD, "storage", "buckets", "describe",
                                   f"gs://{BUCKET}", "--project=" + PROJECT,
                                   "--format=yaml")
    if bucket_rc == 0:
        def bucket_has(text):
            return text.lower() in bucket_out.lower()
        checks = [
            ("location: us-central1", "Bucket is in us-central1"),
            ("default_storage_class: standard", "Bucket storage class is STANDARD"),
            ("public_access_prevention: enforced", "Bucket public access prevention is enforced"),
            ("uniform_bucket_level_access: true", "Bucket uses uniform access"),
            ("retentionDurationSeconds: '0'", "Bucket soft delete is off"),
        ]
        for yaml_snippet, msg in checks:
            check(bucket_has(yaml_snippet), msg)
    else:
        fail(f"Bucket gs://{BUCKET} did not respond")

    # Artifact Registry
    repo_fmt, _, repo_rc = run(GCLOUD, "artifacts", "repositories", "describe",
                               REPO, "--location=" + REGION, "--project=" + PROJECT,
                               "--format=value(format)")
    if repo_fmt == "DOCKER":
        pass_(f"Artifact Registry {REPO} is a Docker repository in {REGION}")
    else:
        fail(f"Artifact Registry {REPO} is missing or not a Docker repository (got '{repo_fmt}')")

    # Secret Manager
    sec_out, _, _ = run(GCLOUD, "secrets", "list", "--project=" + PROJECT,
                        "--format=value(name)")
    sec_count = len([l for l in sec_out.splitlines() if l.strip()])
    if sec_count == 0:
        pass_("Secret Manager has no secrets")
    elif sec_count <= 6:
        note(f"Secret Manager has {sec_count} secret(s), inside the free 6 versions")
    else:
        fail(f"Secret Manager has {sec_count} secrets, past the free 6 versions")

    # Cloud Run
    run_out, _, _ = run(GCLOUD, "run", "services", "list",
                        "--project=" + PROJECT, "--format=value(metadata.name)")
    run_count = len([l for l in run_out.splitlines() if l.strip()])
    if run_count == 0:
        pass_("No Cloud Run service is deployed")
    else:
        fail(f"Cloud Run already has {run_count} service(s). Issue #9 deploys the service.")

    # Git: no secrets tracked
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tracked_out = subprocess.run(
        ["git", "-C", root, "ls-files"],
        capture_output=True, text=True
    ).stdout
    secret_patterns = [".env$", "service-account.*\\.json$",
                       "credentials.*\\.json$", "\\.pem$", "\\.key$"]
    import re
    found = []
    for line in tracked_out.splitlines():
        for pat in secret_patterns:
            if re.search(pat, line):
                found.append(line)
    if not found:
        pass_("Git tracks no credential file")
    else:
        fail("Git tracks credential files:")
        for f in found:
            print(f"  {f}", file=sys.stderr)

    # Budget
    acct_out, _, acct_rc = run(GCLOUD, "billing", "projects", "describe", PROJECT,
                               "--format=value(billingAccountName)")
    if acct_rc == 0 and acct_out.startswith("billingAccounts/"):
        budget_id = acct_out.split("/", 1)[1]
        bud_out, bud_err, bud_rc = run(
            GCLOUD, "billing", "budgets", "list",
            "--billing-account=" + budget_id,
            "--billing-project=" + PROJECT,
            "--format=value(displayName)"
        )
        if bud_rc == 0:
            if BUDGET_NAME in bud_out:
                pass_(f"Budget {BUDGET_NAME} exists")
            else:
                _budget_blocked = 1
                note(f"Budget {BUDGET_NAME} is missing. A billing administrator needs to create it.")
        else:
            if "does not have permission" in bud_err:
                _budget_blocked = 1
                note(f"Cannot manage billing account {budget_id}. Budget alert not confirmed.")
            else:
                fail(f"Budget list failed: {bud_err}")
    else:
        fail("Could not read the linked billing account")

    # ── Summary ─────────────────────────────────────────────────────────────
    print()
    if _failures > 0:
        print(f"{_failures} check(s) failed")
        sys.exit(1)
    if _budget_blocked:
        print("Foundation matches. Budget alert is still blocked.")
        sys.exit(2)
    print("Foundation matches, including the budget alert.")
    sys.exit(0)


if __name__ == "__main__":
    main()
