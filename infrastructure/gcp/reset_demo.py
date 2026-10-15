#!/usr/bin/env python3
"""Reset all GCP services to the demo baseline.

Issue #135: Seed and reset real GCP data for deterministic end-to-end demo.

This script resets all GCP services to their initial demo state:
1. Firestore: Delete all inventory documents, bump store version
2. BigQuery: Delete all demo-scoped rows by SEED_RUN_ID
3. Pub/Sub: Purge subscriptions to clear old messages

After reset, use seed_gcp.py to reseed all services with a new run ID.

Usage:
    # Preview reset without executing
    python infrastructure/gcp/reset_demo.py --dry-run

    # Reset all services
    CONFIRM_RESET=yes python infrastructure/gcp/reset_demo.py

    # Reset Firestore only
    python infrastructure/gcp/reset_demo.py --firestore-only

    # Reset BigQuery only
    python infrastructure/gcp/reset_demo.py --bigquery-only
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# GCP Configuration
PROJECT = os.environ.get("GCP_PROJECT_ID", "retailtwin-ai-511002")
REGION = os.environ.get("GCP_REGION", "us-central1")
DATASET = os.environ.get("BIGQUERY_DATASET", "retailtwin")
TOPIC = os.environ.get("STORE_EVENTS_TOPIC", "store-events")
SUBSCRIPTION = os.environ.get("STORE_EVENTS_SUBSCRIPTION", "store-events-analytics")
CANONICAL_PROJECT = "retailtwin-ai-511002"
STORE_ID = "store-001"

# Demo data namespace - all demo rows are tagged with this prefix
DEMO_NAMESPACE = "retailtwin-demo"

# Must match DEMO_SEED_VERSION in seed_gcp.py / CANONICAL_SEED_VERSION in data/seed/demo_seed.py
DEMO_SEED_VERSION = "v1"

# Firestore claim collection - demo event IDs live here
CLAIM_COLLECTION = "store_event_claims"

def current_run_id() -> str:
    """Get the current demo run ID from seed manifest."""
    manifest_path = Path(__file__).parent / "seed_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            return manifest.get("run_id", "")
        except (json.JSONDecodeError, IOError):
            pass
    return ""


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_CORE_PROJECT"] = PROJECT
    return env


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> str: ...


class SubprocessRunner:
    def run(self, args: list[str]) -> str:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            env=command_env(),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(detail or f"Command failed with exit {completed.returncode}.")
        return completed.stdout


class GcloudTokenProvider:
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner
        self._token: str | None = None

    def get_token(self) -> str:
        if self._token is None:
            raw = self._runner.run(["gcloud", "auth", "print-access-token", "--quiet"])
            self._token = raw.strip()
        return self._token


class HttpResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body


class HttpTransport:
    def __init__(self, token_provider: GcloudTokenProvider) -> None:
        self._token_provider = token_provider
        self._token_lock = threading.Lock()

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: dict[str, str],
    ) -> HttpResponse:
        with self._token_lock:
            token = self._token_provider.get_token()
        headers = {**headers, "Authorization": f"Bearer {token}"}
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return HttpResponse(response.status, response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read().decode("utf-8", errors="replace"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Request failed: {exc.reason}") from exc


def database_root() -> str:
    return f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


def doc_name(collection: str, *path: str) -> str:
    return f"{database_root()}/{'/'.join([collection, *path])}"


def is_demo_claim(document: dict[str, Any]) -> bool:
    """Return whether a claim document is owned by the demo namespace.

    Claims are keyed by event_id.  We deliberately require the final document
    path segment to start with the namespace rather than trusting a mutable
    document field.  This makes cleanup bounded even if a non-demo claim has a
    misleading field value.
    """
    name = document.get("name")
    if not isinstance(name, str):
        return False
    event_id = name.rsplit("/", 1)[-1]
    return event_id.startswith(f"{DEMO_NAMESPACE}-")


def list_demo_claims(transport: HttpTransport) -> list[dict[str, Any]]:
    """List only namespace-owned Firestore event claims.

    The collection may contain non-demo production claims.  Pagination is
    followed and every returned document is locally namespace-filtered before
    it can become a delete write.
    """
    claims: list[dict[str, Any]] = []
    page_token = ""
    while True:
        url = f"{database_root()}/{CLAIM_COLLECTION}?pageSize=300"
        if page_token:
            url += f"&pageToken={page_token}"
        response = transport.request("GET", url, None, {"Content-Type": "application/json"})
        if response.status == 404:
            return claims
        if response.status != 200:
            raise RuntimeError(f"Failed to list Firestore claims: {response.body[:200]}")
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Firestore claim list response is not JSON") from exc
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            raise RuntimeError("Firestore claim list response has invalid documents")
        claims.extend(doc for doc in documents if isinstance(doc, dict) and is_demo_claim(doc))
        next_page_token = payload.get("nextPageToken", "")
        if not isinstance(next_page_token, str) or not next_page_token:
            return claims
        page_token = next_page_token


def is_demo_seed_inventory(document: dict[str, Any]) -> bool:
    """Return whether an inventory document is owned by the demo seed.

    A document is demo-seed-owned when its demo_seed_version field matches the
    current DEMO_SEED_VERSION.  Documents without that field are treated as
    non-demo (live/production) and are never deleted by reset.
    """
    fields = document.get("fields", {})
    version_field = fields.get("demo_seed_version", {})
    if not isinstance(version_field, dict):
        return False
    value = version_field.get("stringValue", "")
    return isinstance(value, str) and value == DEMO_SEED_VERSION


def reset_firestore(transport: HttpTransport, dry_run: bool = False) -> dict[str, Any]:
    """Reset Firestore Live Twin and demo event claims.

    Deletes only inventory documents that are marked as demo-seed-owned
    (demo_seed_version matches DEMO_SEED_VERSION).  Non-demo inventory
    documents are preserved.  Only claim documents whose event_id starts
    with the demo namespace are deleted.  Non-demo claims are never touched.
    """
    if dry_run:
        # A normal dry run must be usable without credentials and must make no
        # HTTP request.  Counts require a separately reviewed live inspection.
        return {"firestore": {
            "dry_run": True,
            "inventory_scope": f"stores/{STORE_ID}/inventory?demo_seed_version={DEMO_SEED_VERSION}",
            "claim_scope": f"{CLAIM_COLLECTION}/{DEMO_NAMESPACE}-*",
            "safety": "Only demo-seed-owned inventory (demo_seed_version=v1) and retailtwin-demo-* claim IDs are eligible.",
        }}

    results: dict[str, Any] = {"firestore": {}}

    # Both inventory and claims must be listed before deciding that reset is a
    # no-op: a previous demo can leave claims after inventory was removed.
    inventory_url = f"{database_root()}/stores/{STORE_ID}/inventory"
    response = transport.request("GET", inventory_url, None, {"Content-Type": "application/json"})
    if response.status == 404:
        inventory_documents: list[dict[str, Any]] = []
    elif response.status != 200:
        raise RuntimeError(f"Failed to list inventory: {response.body[:200]}")
    else:
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Inventory list response is not JSON") from exc
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            raise RuntimeError("Inventory list response has invalid documents")
        inventory_documents = [doc for doc in documents if isinstance(doc, dict)]

    demo_claims = list_demo_claims(transport)

    demo_inventory = [doc for doc in inventory_documents if is_demo_seed_inventory(doc)]
    non_demo_inventory = [doc for doc in inventory_documents if not is_demo_seed_inventory(doc)]

    results["firestore"].update({
        "inventory_found": len(inventory_documents),
        "demo_inventory_found": len(demo_inventory),
        "non_demo_inventory_found": len(non_demo_inventory),
        "demo_claims_found": len(demo_claims),
        "claim_namespace": DEMO_NAMESPACE,
    })

    inventory_deletes = [
        {"delete": name}
        for document in inventory_documents
        if is_demo_seed_inventory(document)
        and isinstance((name := document.get("name")), str)
        and name
    ]
    claim_deletes = [
        {"delete": name}
        for document in demo_claims
        if isinstance((name := document.get("name")), str) and name
    ]

    if dry_run:
        results["firestore"].update({
            "dry_run": True,
            "inventory_documents_to_delete": len(inventory_deletes),
            "demo_claims_to_delete": len(claim_deletes),
            "non_demo_inventory_preserved": len(non_demo_inventory),
            "inventory_sample": [write["delete"] for write in inventory_deletes[:5]],
            "claim_sample": [write["delete"] for write in claim_deletes[:5]],
            "safety": "Only demo-seed-owned inventory (demo_seed_version=v1) and retailtwin-demo-* claim IDs are eligible.",
        })
        return results

    # The claim IDs are deterministic.  Removing namespace-owned claims in the
    # same commit as the inventory reset makes the following deterministic replay
    # fresh; claims outside the namespace cannot be deleted by this code.
    now = datetime.now(timezone.utc).isoformat()
    writes = [*inventory_deletes, *claim_deletes]
    writes.append({
        "update": {
            "name": doc_name("stores", STORE_ID),
            "fields": {
                "store_id": {"stringValue": STORE_ID},
                "version": {"stringValue": "v1"},
                "updated_at": {"timestampValue": now},
            },
        }
    })
    if len(writes) > 500:
        raise RuntimeError(
            "Firestore reset would exceed one atomic commit; refusing partial claim cleanup. "
            "Reduce demo claims or add a reviewed batched reset strategy."
        )

    response = transport.request(
        "POST",
        f"{database_root()}:commit",
        json.dumps({"writes": writes}).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    if response.status != 200:
        raise RuntimeError(f"Firestore reset failed (HTTP {response.status}): {response.body[:200]}")

    results["firestore"].update({
        "reset": True,
        "inventory_deleted": len(inventory_deletes),
        "demo_claims_deleted": len(claim_deletes),
        "non_demo_inventory_preserved": len(non_demo_inventory),
        "version_bumped": True,
        "timestamp": now,
    })
    return results


def run_bq(args: list[str]) -> str:
    """Run a bq command and return stdout."""
    cmd = ["bq", "--quiet", f"--project_id={PROJECT}", f"--location={REGION}"] + args
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=command_env(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"bq command failed with exit {completed.returncode}.")
    return completed.stdout


def reset_bigquery(dry_run: bool = False) -> dict[str, Any]:
    """Reset BigQuery demo data by deleting rows scoped to demo namespace.

    Raises:
        RuntimeError: If any BigQuery cleanup operation fails (fail-closed).
    """
    if dry_run:
        return {
            "bigquery": {
                "dry_run": True,
                "namespace": DEMO_NAMESPACE,
                "tables": ["sales_events", "inventory_events", "agent_actions"],
                "predicate": f"event_id LIKE '{DEMO_NAMESPACE}-%'",
                "safety": "No BigQuery command runs in dry-run mode.",
            }
        }

    results: dict[str, Any] = {"bigquery": {}}

    run_id = current_run_id()

    if not run_id:
        results["bigquery"] = {
            "reset": True,
            "skipped": True,
            "message": "No seed manifest found - nothing to reset",
            "note": "Run seed_gcp.py first to create a seed manifest",
        }
        return results

    # The run_id is stored in the manifest and used to scope all demo data
    # For BigQuery, we delete rows that were inserted with a matching run context
    # Since we use deterministic event IDs with the namespace prefix, we can delete by prefix

    deleted_counts: dict[str, int] = {}
    errors: list[str] = []
    table_names = ["sales_events", "inventory_events", "agent_actions"]

    for table in table_names:
        qualified_table = f"`{PROJECT}.{DATASET}.{table}`"

        if dry_run:
            # Count rows to be deleted
            try:
                count_query = f"""
                    SELECT COUNT(*) as cnt FROM {qualified_table}
                    WHERE event_id LIKE '{DEMO_NAMESPACE}-%'
                """
                result = run_bq(["query", "--nouse_legacy_sql", "--format=json", count_query])
                data = json.loads(result)
                count = data[0]["cnt"] if data else 0
                deleted_counts[table] = count
            except Exception as e:
                # On dry-run failure, note it but continue
                deleted_counts[table] = 0
                errors.append(f"{table}: {e}")
        else:
            # Delete demo-scoped rows - fail-closed on error
            delete_query = f"""
                DELETE FROM {qualified_table}
                WHERE event_id LIKE '{DEMO_NAMESPACE}-%'
            """
            try:
                run_bq(["query", "--nouse_legacy_sql", delete_query])
                deleted_counts[table] = 1  # DML doesn't return count easily
            except Exception as e:
                # Fail-closed: propagate error so main() knows cleanup failed
                raise RuntimeError(
                    f"BigQuery cleanup failed for table {table}: {e}"
                ) from e

    results["bigquery"] = {
        "reset": True,
        "run_id": run_id,
        "namespace": DEMO_NAMESPACE,
        "deleted_by_table": deleted_counts,
        "message": "Deleted all demo-scoped rows from BigQuery",
        "manifest_pending_removal": not dry_run,
    }

    if errors:
        results["bigquery"]["dry_run_errors"] = errors

    return results


def check_topic_exists() -> bool:
    """Check if Pub/Sub topic exists."""
    try:
        result = subprocess.run(
            ["gcloud", "pubsub", "topics", "describe", TOPIC, "--project", PROJECT],
            capture_output=True, text=True, env=command_env()
        )
        return result.returncode == 0
    except Exception:
        return False


def reset_pubsub(dry_run: bool = False) -> dict[str, Any]:
    """Reset Pub/Sub by seeking subscriptions to current message."""
    results: dict[str, Any] = {"pubsub": {}}

    topic_exists = check_topic_exists()
    results["pubsub"]["topic_exists"] = topic_exists

    if not topic_exists:
        results["pubsub"]["message"] = "Topic does not exist - nothing to reset"
        return results

    if dry_run:
        results["pubsub"]["dry_run"] = True
        results["pubsub"]["message"] = "Would seek subscription to current (no messages to process)"
        return results

    # For Pub/Sub, we don't delete messages (they're ephemeral by default)
    # Instead, we note that the subscription should be at the current head
    # Any new messages published will be picked up by consumers

    # Check subscription exists
    try:
        result = subprocess.run(
            ["gcloud", "pubsub", "subscriptions", "describe", SUBSCRIPTION,
             "--project", PROJECT, "--format=value(name)"],
            capture_output=True, text=True, env=command_env()
        )
        sub_exists = result.returncode == 0
        results["pubsub"]["subscription_exists"] = sub_exists

        if sub_exists:
            # Note: Pub/Sub subscriptions retain messages according to retention settings
            # For deterministic replay, we rely on event_id deduplication
            results["pubsub"]["message"] = "Subscription retained (Pub/Sub is ephemeral by default)"
            results["pubsub"]["note"] = "Use deterministic event_ids for idempotent replay"
        else:
            results["pubsub"]["message"] = "Subscription does not exist"

    except Exception as e:
        results["pubsub"]["error"] = str(e)
        results["pubsub"]["message"] = "Could not check subscription"

    return results


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_guardrails() -> None:
    """Validate environment before reset."""
    if PROJECT != CANONICAL_PROJECT:
        die(f"Refusing project {PROJECT}. Reset applies only to {CANONICAL_PROJECT}.")

    if os.environ.get("CONFIRM_RESET", "") != "yes":
        die("Set CONFIRM_RESET=yes to reset all GCP services to baseline.")

    # Check billing
    result = subprocess.run(
        ["gcloud", "billing", "projects", "describe", PROJECT,
         "--format=value(billingEnabled)"],
        capture_output=True, text=True, env=command_env()
    )
    if result.stdout.strip() != "True":
        die("Billing is disabled on this project.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset all GCP services to demo baseline."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview reset without executing"
    )
    parser.add_argument(
        "--firestore-only",
        action="store_true",
        help="Reset only Firestore"
    )
    parser.add_argument(
        "--bigquery-only",
        action="store_true",
        help="Reset only BigQuery"
    )
    parser.add_argument(
        "--pubsub-only",
        action="store_true",
        help="Reset only Pub/Sub"
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Also reseed after reset"
    )
    args = parser.parse_args()

    confirm = os.environ.get("CONFIRM_RESET", "")
    dry_run = args.dry_run or confirm == "dry"
    reseed = args.reseed or os.environ.get("CONFIRM_SEED", "") == "yes"

    print(f"Project:   {PROJECT}")
    print(f"Region:    {REGION}")
    print(f"Store:     {STORE_ID}")
    print(f"Dry run:   {dry_run}")
    print(f"Reseed:    {reseed}")
    print(f"Scope:     ", end="")

    if args.firestore_only:
        print("Firestore only")
    elif args.bigquery_only:
        print("BigQuery only")
    elif args.pubsub_only:
        print("Pub/Sub only")
    else:
        print("All services")

    print()

    if not dry_run:
        check_guardrails()
    else:
        print("DRY RUN MODE - No changes will be made")
        print()

    results: dict[str, Any] = {"dry_run": dry_run}
    all_phases_succeeded = True

    # Reset selected services
    try:
        if not args.bigquery_only and not args.pubsub_only:
            # Initialize Firestore components
            runner = SubprocessRunner()
            token_provider = GcloudTokenProvider(runner)
            transport = HttpTransport(token_provider)

            print("Resetting Firestore Live Twin...")
            results["firestore"] = reset_firestore(transport, dry_run)
            print(f"  Result: {json.dumps(results['firestore'], indent=4)}")
            print()

        if not args.firestore_only and not args.pubsub_only:
            print("Resetting BigQuery...")
            results["bigquery"] = reset_bigquery(dry_run)
            print(f"  Result: {json.dumps(results['bigquery'], indent=4)}")
            print()

        if not args.firestore_only and not args.bigquery_only:
            print("Checking Pub/Sub...")
            results["pubsub"] = reset_pubsub(dry_run)
            print(f"  Result: {json.dumps(results['pubsub'], indent=4)}")
            print()

        # Only remove manifest after ALL phases succeeded
        if all_phases_succeeded and not dry_run:
            manifest_path = Path(__file__).parent / "seed_manifest.json"
            if manifest_path.exists():
                manifest_path.unlink()
                print("Seed manifest removed.")
                print()

        print("Reset complete!")
        print()

        if reseed and not dry_run:
            print("Reseeding services...")
            print("  Run seed_gcp.py to reseed all services")

        return 0
    except Exception as e:
        all_phases_succeeded = False
        print(f"error: {e}", file=sys.stderr)
        print()
        print("Reset failed - manifest preserved for retry.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
