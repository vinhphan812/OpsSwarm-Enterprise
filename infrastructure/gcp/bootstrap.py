#!/usr/bin/env python3
"""
Apply the day-0 Google Cloud foundation for issue #5.
Idempotent. Creates no keys, documents, subscriptions, secrets, or model calls.
See infrastructure/gcp/README.md.

Windows-compatible version: calls gcloud.cmd and bq.cmd directly via subprocess.
"""

import subprocess, sys, os, json, tempfile, shutil, textwrap, re
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
PROJECT = os.environ.get("GCP_PROJECT_ID", "retailtwin-ai-511002")
REGION  = os.environ.get("GCP_REGION", "us-central1")
DATABASE = os.environ.get("FIRESTORE_DATABASE", "(default)")
TOPIC    = os.environ.get("STORE_EVENTS_TOPIC", "store-events")
DATASET  = os.environ.get("BIGQUERY_DATASET", "retailtwin")
BUCKET   = os.environ.get("GCS_BUCKET", "retailtwin-ai-511002-assets")
REPO     = os.environ.get("ARTIFACT_REGISTRY_REPO", "retailtwin")
CANONICAL_PROJECT = "retailtwin-ai-511002"
BUDGET_NAME = "retailtwin-dev-guard"
API_SA_ID   = "retailtwin-api"
AGENT_SA_ID = "retailtwin-agent"
API_SA   = f"{API_SA_ID}@{PROJECT}.iam.gserviceaccount.com"
AGENT_SA = f"{AGENT_SA_ID}@{PROJECT}.iam.gserviceaccount.com"
CONFIRM  = os.environ.get("CONFIRM_GCP_BOOTSTRAP", "")

# ── Helpers ─────────────────────────────────────────────────────────────────
GCLOUD = "gcloud.cmd"
BQ     = "bq.cmd"
REQUIRED_APIS_FILE = Path(__file__).with_name("required-apis.txt")


def required_apis():
    try:
        apis = [
            line.strip()
            for line in REQUIRED_APIS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except OSError as exc:
        die(f"Cannot read required API manifest {REQUIRED_APIS_FILE}: {exc}")
    if not apis:
        die(f"Required API manifest is empty: {REQUIRED_APIS_FILE}")
    return apis

def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)

def run(*args, check=True, capture=True, project=True, **kwargs):
    """Run a gcloud/bq command. Returns CompletedProcess on success."""
    cmd = list(args)
    if project and "--project" not in cmd and "bq" not in cmd[0]:
        cmd.extend(["--project", PROJECT])
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_CORE_PROJECT"] = PROJECT
    env["CLOUDSDK_BILLING_QUOTA_PROJECT"] = PROJECT
    kwargs.setdefault("env", env)
    kwargs.setdefault("text", True)
    if capture:
        kwargs.setdefault("capture_output", True)
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        cmd_str = " ".join(cmd)
        err = result.stderr or result.stdout or ""
        die(f"Command failed ({result.returncode}): {cmd_str}\n{err}")
    return result

def run_unchecked(*args, **kwargs):
    return run(*args, check=False, capture=False, **kwargs)

def account():
    try:
        return run(GCLOUD, "config", "get-value", "account", check=True).stdout.strip()
    except Exception:
        return "(none)"

# ── Guardrails ─────────────────────────────────────────────────────────────
def check_guardrails():
    if CONFIRM != "yes":
        die("Set CONFIRM_GCP_BOOTSTRAP=yes to apply the foundation.")
    if PROJECT != CANONICAL_PROJECT:
        die(f"Refusing project {PROJECT}. This foundation applies only to {CANONICAL_PROJECT}.")
    if REGION != "us-central1":
        die(f"Refusing region {REGION}. Cloud Storage free tier and this foundation use us-central1.")

    out = run(GCLOUD, "billing", "projects", "describe", PROJECT,
              "--format=value(billingEnabled)", check=True).stdout.strip()
    if out != "True":
        die("Billing is disabled on this project. Free tier still requires a linked billing account.")

# ── Service accounts ────────────────────────────────────────────────────────
def ensure_service_account(sa_id, display, description):
    email = f"{sa_id}@{PROJECT}.iam.gserviceaccount.com"
    result = run_unchecked(GCLOUD, "iam", "service-accounts", "describe", email)
    if result.returncode == 0:
        print(f"Service account exists: {email}")
    else:
        print(f"Creating service account: {email}")
        run(GCLOUD, "iam", "service-accounts", "create", sa_id,
            f"--display-name={display}", f"--description={description}")

def bind_project_role(member, role):
    run(GCLOUD, "projects", "add-iam-policy-binding", PROJECT,
        "--member", member, "--role", role, "--quiet")

# ── APIs ────────────────────────────────────────────────────────────────────
def enable_apis():
    apis = required_apis()
    print(f"Enabling {len(apis)} required APIs")
    run(GCLOUD, "services", "enable", *apis)

# ── Firestore ───────────────────────────────────────────────────────────────
def ensure_firestore():
    print(f"Firestore database {DATABASE}")
    result = run_unchecked(GCLOUD, "firestore", "databases", "describe",
                           "--database", DATABASE)
    if result.returncode == 0:
        print("Firestore database already exists")
    else:
        print("Creating Firestore database")
        run(GCLOUD, "firestore", "databases", "create",
            "--database", DATABASE, "--location", REGION,
            "--edition=standard", "--type=firestore-native",
            "--delete-protection")

# ── Pub/Sub ─────────────────────────────────────────────────────────────────
def ensure_pubsub():
    print(f"Pub/Sub topic {TOPIC}")
    result = run_unchecked(GCLOUD, "pubsub", "topics", "describe", TOPIC)
    if result.returncode != 0:
        print("Creating Pub/Sub topic")
        run(GCLOUD, "pubsub", "topics", "create", TOPIC,
            "--message-storage-policy-allowed-regions", REGION,
            "--labels=app=retailtwin,cost=free-tier")

    # Limit message storage to us-central1 (may race on first create)
    for attempt in range(1, 6):
        result = run_unchecked(GCLOUD, "pubsub", "topics", "update", TOPIC,
                               "--message-storage-policy-allowed-regions", REGION)
        if result.returncode == 0:
            break
        print(f"Topic update raced (attempt {attempt}). Waiting.")
        import time; time.sleep(5)
    else:
        die(f"Could not limit {TOPIC} message storage to {REGION}.")

    # Bind publisher IAM
    run(GCLOUD, "pubsub", "topics", "add-iam-policy-binding", TOPIC,
        "--member", f"serviceAccount:{API_SA}", "--role", "roles/pubsub.publisher",
        "--quiet")

# ── BigQuery ────────────────────────────────────────────────────────────────
def ensure_bigquery():
    print(f"BigQuery dataset {DATASET}")
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    result = subprocess.run(
        [BQ, "--project_id=" + PROJECT, "show", "--dataset", f"{PROJECT}:{DATASET}"],
        capture_output=True, text=True, env=env
    )
    if result.returncode == 0:
        print("Dataset already exists")
    else:
        print("Creating BigQuery dataset")
        subprocess.run(
            [BQ, "--project_id=" + PROJECT, "--location=" + REGION, "mk",
             "--dataset",
             "--description=RetailTwin analytical history. On-demand only. Empty day-0 dataset stays inside the 10 GiB free tier.",
             "--label=app:retailtwin", "--label=cost:free-tier",
             f"{PROJECT}:{DATASET}"],
            check=True, env=env
        )

# ── Cloud Storage ───────────────────────────────────────────────────────────
def ensure_gcs():
    print(f"Cloud Storage bucket {BUCKET}")
    result = run_unchecked(GCLOUD, "storage", "buckets", "describe", f"gs://{BUCKET}")
    if result.returncode == 0:
        print("Bucket already exists")
    else:
        print("Creating Cloud Storage bucket")
        run(GCLOUD, "storage", "buckets", "create", f"gs://{BUCKET}",
            "--location", REGION,
            "--default-storage-class=STANDARD",
            "--uniform-bucket-level-access",
            "--public-access-prevention",
            "--soft-delete-duration=0s")

# ── Artifact Registry ───────────────────────────────────────────────────────
def ensure_artifact_registry():
    print(f"Artifact Registry repository {REPO}")
    result = run_unchecked(GCLOUD, "artifacts", "repositories", "describe",
                           REPO, "--location", REGION)
    if result.returncode == 0:
        print("Repository already exists")
    else:
        print("Creating Artifact Registry repository")
        run(GCLOUD, "artifacts", "repositories", "create", REPO,
            "--repository-format=docker", "--location", REGION,
            "--description=RetailTwin images. Keep this repository under the 0.5 GB free tier.",
            "--labels=app=retailtwin,cost=free-tier")

# ── Budget ─────────────────────────────────────────────────────────────────
def configure_budget():
    print("Budget alert")
    billing_info = run(GCLOUD, "billing", "projects", "describe", PROJECT,
                       "--format=value(billingAccountName)", check=True).stdout.strip()
    account_id = re.sub(r"^billingAccounts/", "", billing_info)
    errfile = tempfile.NamedTemporaryFile(mode='w', suffix='.err', delete=False)
    errfile.close()
    budget_blocked = False
    try:
        env = os.environ.copy()
        env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
        result = subprocess.run(
            [GCLOUD, "billing", "budgets", "list",
             "--billing-account=" + account_id,
             "--billing-project=" + PROJECT,
             "--format=value(displayName)"],
            capture_output=True, text=True, env=env, timeout=30
        )
        if result.returncode == 0:
            names = [n.strip() for n in result.stdout.strip().split("\n") if n.strip()]
            if BUDGET_NAME in names:
                print(f"Budget {BUDGET_NAME} already exists")
                return False
            print(f"Creating budget {BUDGET_NAME} for 25000 VND")
            result2 = subprocess.run(
                [GCLOUD, "billing", "budgets", "create",
                 "--billing-account=" + account_id,
                 "--billing-project=" + PROJECT,
                 "--display-name=" + BUDGET_NAME,
                 "--budget-amount=25000VND",
                 "--calendar-period=month",
                 "--filter-projects=projects/" + PROJECT,
                 "--threshold-rule=percent=0.5",
                 "--threshold-rule=percent=0.9",
                 "--threshold-rule=percent=1.0"],
                capture_output=True, text=True, env=env, timeout=60,
                stderr=subprocess.STDOUT
            )
            if result2.returncode != 0:
                print(f"Could not create the 25000 VND budget: {result2.stdout}", file=sys.stderr)
                raise Exception("budget creation failed")
            return False
        else:
            err = result.stderr or ""
            if "does not have permission" in err:
                print(f"BLOCKED: this account cannot manage billing account {account_id}.", file=sys.stderr)
                print("A billing administrator creates the 25000 VND alert with:", file=sys.stderr)
                print(textwrap.dedent(f"""
                gcloud billing budgets create \\
                  --billing-account={account_id} \\
                  --billing-project={PROJECT} \\
                  --display-name={BUDGET_NAME} \\
                  --budget-amount=25000VND \\
                  --calendar-period=month \\
                  --filter-projects=projects/{PROJECT} \\
                  --threshold-rule=percent=0.5 \\
                  --threshold-rule=percent=0.9 \\
                  --threshold-rule=percent=1.0
                """), file=sys.stderr)
                budget_blocked = True
            else:
                print(f"Budget list failed: {err}", file=sys.stderr)
                budget_blocked = True
    finally:
        try: os.unlink(errfile.name)
        except: pass
    return budget_blocked

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print(f"Project:  {PROJECT}")
    print(f"Region:   {REGION}")
    print(f"Account:  {account()}")
    print()
    print("This will not create service-account keys, Firestore documents, Pub/Sub")
    print("subscriptions, Secret Manager versions, Cloud Run services, or Vertex calls.")
    print()

    check_guardrails()

    enable_apis()
    ensure_service_account(API_SA_ID,   "RetailTwin API runtime",    "Writes Firestore and publishes store events. No key is created.")
    ensure_service_account(AGENT_SA_ID,  "RetailTwin Vertex caller",  "Calls Vertex AI only. Must not write Firestore. No key is created.")

    print("Binding runtime roles")
    bind_project_role(f"serviceAccount:{API_SA}",   "roles/datastore.user")
    bind_project_role(f"serviceAccount:{API_SA}",   "roles/logging.logWriter")
    bind_project_role(f"serviceAccount:{AGENT_SA}",  "roles/aiplatform.user")

    ensure_firestore()
    ensure_pubsub()
    ensure_bigquery()
    ensure_gcs()
    ensure_artifact_registry()
    budget_blocked = configure_budget()

    print()
    print(f"Foundation applied on {PROJECT} in {REGION}.")
    print(f"API identity:   {API_SA}")
    print(f"Agent identity: {AGENT_SA}")
    if budget_blocked:
        print("Budget alert is not configured.")
        sys.exit(2)
    print(f"Budget alert {BUDGET_NAME} is configured.")
    sys.exit(0)

if __name__ == "__main__":
    main()
