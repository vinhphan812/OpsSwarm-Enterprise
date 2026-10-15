#!/usr/bin/env python3
"""Seed all GCP services for the deterministic end-to-end demo.

Issue #135: Seed and reset real GCP data for deterministic end-to-end demo.

This script orchestrates the complete demo data seeding:
1. Firestore: Seeds the Live Twin with canonical products including P017
2. BigQuery: Seeds historical sales context
3. (Optional) Publishes demand-surge events through Pub/Sub

Demo Flow:
    RESET → Firestore baseline → BigQuery context → Pub/Sub event →
    Observer → Investigator → Planner → Simulation → KPI → DCG →
    Live mutation → Verifier → 3D update

Usage:
    # Preview all operations
    python infrastructure/gcp/seed_gcp.py --dry-run

    # Seed all services
    CONFIRM_SEED=yes python infrastructure/gcp/seed_gcp.py

    # Seed and publish events
    CONFIRM_SEED=yes python infrastructure/gcp/seed_gcp.py --publish-events

    # Full reset and seed
    CONFIRM_RESET=yes CONFIRM_SEED=yes python infrastructure/gcp/seed_gcp.py --reset

Canonical Scenario: Weekend Demand Surge / P017
- Store: store-001
- Demand surge SKU: P017
- Baseline: 50 units Friday (12.5/hour)
- Surge: 73 units Saturday (18.25/hour)
- Increase: 46%
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
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
CANONICAL_PROJECT = "retailtwin-ai-511002"

STORE_ID = "store-001"
SKU = "P017"

# Demo namespace for all demo-scoped data
DEMO_NAMESPACE = "retailtwin-demo"
# Must match CANONICAL_SEED_VERSION in data/seed/demo_seed.py
DEMO_SEED_VERSION = "v1"


def demo_event_id(suffix: str) -> str:
    """Create a deterministic event ID with demo namespace."""
    return f"{DEMO_NAMESPACE}-{suffix}"


def create_seed_manifest(run_id: str, counts: dict[str, int]) -> dict[str, Any]:
    """Create and save seed manifest for deterministic reset."""
    manifest = {
        "run_id": run_id,
        "namespace": DEMO_NAMESPACE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "store_id": STORE_ID,
        "sku": SKU,
        "counts": counts,
        "checksums": {
            "p017_friday": 50,  # Expected units on Friday
            "p017_saturday": 73,  # Expected units on Saturday (surge)
        }
    }
    manifest_path = Path(__file__).parent / "seed_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def load_seed_manifest() -> dict[str, Any] | None:
    """Load existing seed manifest if exists."""
    manifest_path = Path(__file__).parent / "seed_manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return None

# Import seed data
from data.seed.demo_seed import DEMO_PRODUCTS, SeedProduct


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_CORE_PROJECT"] = PROJECT
    return env


def bq_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
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


def run_bq(args: list[str]) -> str:
    cmd = ["bq", "--quiet", f"--project_id={PROJECT}", f"--location={REGION}"] + args
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=bq_env(),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "bq command failed")
    return completed.stdout


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_guardrails() -> None:
    if PROJECT != CANONICAL_PROJECT:
        die(f"Refusing project {PROJECT}. Seed applies only to {CANONICAL_PROJECT}.")

    if os.environ.get("CONFIRM_SEED", "") != "yes":
        die("Set CONFIRM_SEED=yes to seed all GCP services.")

    result = subprocess.run(
        ["gcloud", "billing", "projects", "describe", PROJECT,
         "--format=value(billingEnabled)"],
        capture_output=True, text=True, env=command_env()
    )
    if result.stdout.strip() != "True":
        die("Billing is disabled on this project.")


# ─── Firestore Seeding ────────────────────────────────────────────────────────

def _inventory_fields(seed: SeedProduct, now: str) -> dict[str, Any]:
    return {
        "store_id": {"stringValue": STORE_ID},
        "sku": {"stringValue": seed.sku},
        "shelf_id": {"stringValue": seed.shelf_id},
        "slot_id": {"stringValue": seed.slot_id},
        "facings": {"integerValue": str(seed.facings)},
        "shelf_quantity": {"integerValue": str(seed.shelf_quantity)},
        "backroom_quantity": {"integerValue": str(seed.backroom_quantity)},
        "version": {"integerValue": "1"},
        "demo_seed_version": {"stringValue": DEMO_SEED_VERSION},
        "updated_at": {"timestampValue": now},
    }


def _store_fields(now: str) -> dict[str, Any]:
    return {
        "store_id": {"stringValue": STORE_ID},
        "version": {"stringValue": "v1"},
        "updated_at": {"timestampValue": now},
    }


def check_existing_state(transport: HttpTransport) -> dict[str, Any]:
    """Check if there's existing live state in Firestore."""
    results = {"has_existing": False, "store_count": 0, "inventory_count": 0}

    # Check store
    store_url = f"{database_root()}/stores/{STORE_ID}"
    resp = transport.request("GET", store_url, None, {"Content-Type": "application/json"})
    if resp.status == 200:
        results["has_existing"] = True
        results["store_count"] = 1

    # Check inventory
    inv_url = f"{database_root()}/stores/{STORE_ID}/inventory"
    resp = transport.request("GET", inv_url, None, {"Content-Type": "application/json"})
    if resp.status == 200:
        try:
            data = json.loads(resp.body)
            docs = data.get("documents", [])
            results["inventory_count"] = len(docs)
            if docs:
                results["has_existing"] = True
        except json.JSONDecodeError:
            pass

    return results


def seed_firestore(transport: HttpTransport, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    """Seed Firestore Live Twin with demo products."""
    if dry_run:
        # Dry run is intentionally offline: it validates deterministic payload
        # construction without acquiring credentials or touching Firestore.
        return {
            "dry_run": True,
            "stores_to_write": 1,
            "inventory_to_write": len(DEMO_PRODUCTS),
            "claim_strategy": "reset_demo.py deletes only retailtwin-demo-* claims before deterministic replay",
        }

    # Check for existing state first
    existing = check_existing_state(transport)

    if existing["has_existing"] and not force:
        return {
            "skipped": True,
            "message": "Existing live state detected. Use --force to overwrite.",
            "existing_state": {
                "stores": existing["store_count"],
                "inventory": existing["inventory_count"],
            },
            "safety": "blocked - existing state detected"
        }

    if dry_run:
        return {
            "dry_run": True,
            "stores_to_write": 1,
            "inventory_to_write": len(DEMO_PRODUCTS),
            "would_overwrite": existing["has_existing"],
        }

    now = datetime.now(timezone.utc).isoformat()
    writes: list[dict[str, Any]] = []

    # Upsert store metadata
    store_doc = doc_name("stores", STORE_ID)
    writes.append({"update": {"name": store_doc, "fields": _store_fields(now)}})

    # Upsert all inventory documents
    for seed in DEMO_PRODUCTS:
        inv_doc = doc_name("stores", STORE_ID, "inventory", seed.sku)
        writes.append({"update": {"name": inv_doc, "fields": _inventory_fields(seed, now)}})

    if dry_run:
        return {
            "dry_run": True,
            "products": len(DEMO_PRODUCTS),
            "p017": {
                "sku": SKU,
                "shelf_quantity": next(p.shelf_quantity for p in DEMO_PRODUCTS if p.sku == SKU),
                "backroom_quantity": next(p.backroom_quantity for p in DEMO_PRODUCTS if p.sku == SKU),
                "facings": next(p.facings for p in DEMO_PRODUCTS if p.sku == SKU),
            }
        }

    payload = {"writes": writes}
    url = f"{database_root()}:commit"
    raw = json.dumps(payload).encode("utf-8")

    response = transport.request("POST", url, raw, {"Content-Type": "application/json"})

    if response.status != 200:
        try:
            error = json.loads(response.body)
            raise RuntimeError(f"Firestore seed failed: {error.get('error', {}).get('message', response.body)}")
        except json.JSONDecodeError:
            raise RuntimeError(f"Firestore seed failed (HTTP {response.status}): {response.body[:200]}")

    return {
        "seeded_products": len(DEMO_PRODUCTS),
        "store_id": STORE_ID,
        "version": "v1",
        "p017": {
            "sku": SKU,
            "shelf_quantity": next(p.shelf_quantity for p in DEMO_PRODUCTS if p.sku == SKU),
            "backroom_quantity": next(p.backroom_quantity for p in DEMO_PRODUCTS if p.sku == SKU),
            "facings": next(p.facings for p in DEMO_PRODUCTS if p.sku == SKU),
        }
    }


# ─── BigQuery Seeding ──────────────────────────────────────────────────────────

def qualified_table(table: str) -> str:
    return f"`{PROJECT}.{DATASET}.{table}`"


def format_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_p017_context() -> list[dict[str, Any]]:
    """Generate P017 historical context showing weekend surge pattern.

    All event_ids use DEMO_NAMESPACE prefix for bounded reset capability.
    """
    events = []
    base_date = datetime(2026, 9, 12, tzinfo=timezone.utc)

    for week in range(4):
        week_start = base_date + timedelta(weeks=week)

        # Friday surge
        for i, hour in enumerate([8, 9, 10, 11]):
            events.append({
                "event_id": demo_event_id(f"hist-p017-w{week}-fri-{hour}"),
                "correlation_id": demo_event_id(f"hist-week{week}"),
                "event_type": "sale.completed",
                "store_id": STORE_ID,
                "sku": SKU,
                "quantity": 10 + (i % 2) * 2,
                "occurred_at": format_timestamp(week_start + timedelta(hours=hour)),
                "source": "historical-pos",
            })

        # Saturday surge (higher)
        for i, hour in enumerate([8, 9, 10, 11, 12]):
            events.append({
                "event_id": demo_event_id(f"hist-p017-w{week}-sat-{hour}"),
                "correlation_id": demo_event_id(f"hist-week{week}"),
                "event_type": "sale.completed",
                "store_id": STORE_ID,
                "sku": SKU,
                "quantity": 11 + (i % 3) * 2,
                "occurred_at": format_timestamp(week_start + timedelta(days=1, hours=hour)),
                "source": "historical-pos",
            })

        # Weekday baseline
        for day_offset in [3, 4, 5]:
            events.append({
                "event_id": demo_event_id(f"hist-p017-w{week}-day{day_offset}"),
                "correlation_id": demo_event_id(f"hist-week{week}"),
                "event_type": "sale.completed",
                "store_id": STORE_ID,
                "sku": SKU,
                "quantity": 8,
                "occurred_at": format_timestamp(week_start + timedelta(days=day_offset, hours=10)),
                "source": "historical-pos",
            })

    return events


def seed_bigquery(dry_run: bool = False) -> dict[str, Any]:
    """Seed BigQuery with historical context."""
    events = generate_p017_context()

    if dry_run:
        return {
            "dry_run": True,
            "events_to_seed": len(events),
            "sample": events[:3],
        }

    table = qualified_table("sales_events")
    inserted = 0
    for event in events:
        sql = f"""
            INSERT INTO {table}
            (event_id, correlation_id, event_type, store_id, sku, quantity, occurred_at, source, ingested_at)
            SELECT
                @event_id, @correlation_id, @event_type, @store_id, @sku, @quantity,
                @occurred_at, @source, CURRENT_TIMESTAMP()
            FROM (SELECT 1)
            WHERE NOT EXISTS (SELECT 1 FROM {table} WHERE event_id = @event_id)
        """
        try:
            run_bq([
                "query", "--nouse_legacy_sql", "--format=json",
                f"--parameter=event_id:STRING:{event['event_id']}",
                f"--parameter=correlation_id:STRING:{event['correlation_id']}",
                f"--parameter=event_type:STRING:{event['event_type']}",
                f"--parameter=store_id:STRING:{event['store_id']}",
                f"--parameter=sku:STRING:{event['sku']}",
                f"--parameter=quantity:INT64:{event['quantity']}",
                f"--parameter=occurred_at:TIMESTAMP:{event['occurred_at']}",
                f"--parameter=source:STRING:{event['source']}",
                "--maximum_bytes_billed=100000000",
                sql,
            ])
        except Exception as exc:
            # NOT EXISTS makes an existing matching deterministic ID safe.  A
            # command failure is not evidence of a duplicate, so do not report
            # it as skipped or write a success manifest after a partial seed.
            raise RuntimeError(
                "BigQuery seed failed after "
                f"{inserted}/{len(events)} event(s); failed event_id={event['event_id']}. "
                "The manifest was not written; reset the demo namespace before retrying."
            ) from exc
        inserted += 1

    return {"table": "sales_events", "inserted": inserted, "expected": len(events)}


# ─── Pub/Sub Event Publishing ─────────────────────────────────────────────────

CORRELATION_ID = "run-weekend-demand-surge-1"
SOURCE = "synthetic-pos"
BASELINE_START = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
SURGE_START = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
WINDOW_HOURS = 4


def canonical_body(event: dict[str, Any]) -> str:
    payload = {
        "correlation_id": event["correlation_id"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "occurred_at": event["occurred_at"],
        "quantity": event["quantity"],
        "sku": event["sku"],
        "source": event["source"],
        "store_id": event["store_id"],
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def generate_demo_events() -> list[dict[str, Any]]:
    """Generate all demo events (baseline + surge).

    All event_ids use DEMO_NAMESPACE prefix for bounded reset capability.
    """
    events = []

    # Baseline (Friday)
    quantities = (10, 10, 10, 10, 10)
    step = timedelta(hours=WINDOW_HOURS) / len(quantities)
    for index, quantity in enumerate(quantities, start=1):
        events.append({
            "event_id": demo_event_id(f"evt-p017-base-{index:04d}"),
            "correlation_id": demo_event_id(CORRELATION_ID),
            "event_type": "sale.completed",
            "store_id": STORE_ID,
            "sku": SKU,
            "quantity": quantity,
            "occurred_at": (BASELINE_START + step * (index - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": SOURCE,
        })

    # Surge (Saturday)
    quantities = (9, 9, 9, 9, 9, 9, 9, 10)
    step = timedelta(hours=WINDOW_HOURS) / len(quantities)
    for index, quantity in enumerate(quantities, start=1):
        events.append({
            "event_id": demo_event_id(f"evt-p017-surge-{index:04d}"),
            "correlation_id": demo_event_id(CORRELATION_ID),
            "event_type": "sale.completed",
            "store_id": STORE_ID,
            "sku": SKU,
            "quantity": quantity,
            "occurred_at": (SURGE_START + step * (index - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": SOURCE,
        })

    return events


def publish_event(event: dict[str, Any]) -> dict[str, Any]:
    """Publish one event to the store-events topic."""
    body = canonical_body(event)

    completed = subprocess.run(
        [
            "gcloud", "pubsub", "topics", "publish", TOPIC,
            "--project", PROJECT,
            "--quiet",
            f"--message={body}",
            f"--attribute=correlation_id={event['correlation_id']}",
            f"--attribute=event_id={event['event_id']}",
            f"--attribute=event_type={event['event_type']}",
            f"--attribute=store_id={event['store_id']}",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=command_env(),
    )

    if completed.returncode != 0:
        raise RuntimeError(f"Publish failed: {completed.stderr}")

    return {"published": event["event_id"], "message_id": completed.stdout.strip()}


def publish_events(events: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    """Publish demo events to Pub/Sub."""
    if dry_run:
        return {"dry_run": True, "events": len(events), "sample": events[:3]}

    published = []
    errors = []

    for event in events:
        try:
            result = publish_event(event)
            published.append(result)
        except Exception as e:
            errors.append({"event_id": event["event_id"], "error": str(e)})

    return {"published": len(published), "errors": len(errors)}


# ─── Main Orchestration ────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed all GCP services for the deterministic demo."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all operations without executing"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset services before seeding"
    )
    parser.add_argument(
        "--publish-events",
        action="store_true",
        help="Also publish demo events to Pub/Sub"
    )
    parser.add_argument(
        "--firestore-only",
        action="store_true",
        help="Seed only Firestore"
    )
    parser.add_argument(
        "--bigquery-only",
        action="store_true",
        help="Seed only BigQuery"
    )
    parser.add_argument(
        "--pubsub-only",
        action="store_true",
        help="Publish only Pub/Sub events"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing live state"
    )
    args = parser.parse_args()

    confirm = os.environ.get("CONFIRM_SEED", "")
    dry_run = args.dry_run or confirm == "dry"

    print("=" * 60)
    print("RETAILTWIN AI - DEMO DATA SEEDER")
    print("=" * 60)
    print(f"Project:     {PROJECT}")
    print(f"Region:      {REGION}")
    print(f"Dataset:     {DATASET}")
    print(f"Topic:       {TOPIC}")
    print(f"Store:       {STORE_ID}")
    print(f"Dry run:     {dry_run}")
    print(f"Reset first: {args.reset}")
    print(f"Publish:     {args.publish_events}")
    print()

    if not dry_run:
        check_guardrails()
    else:
        print("DRY RUN MODE - No changes will be made")
        print()

    # Show scenario info
    print("SCENARIO: Weekend Demand Surge / P017")
    print("-" * 40)
    print(f"  Baseline (Friday):   50 units in 4 hours (12.5/hr)")
    print(f"  Surge (Saturday):   73 units in 4 hours (18.25/hr)")
    print(f"  Increase:            46%")
    print(f"  Correlation ID:      {CORRELATION_ID}")
    print()

    results: dict[str, Any] = {}

    try:
        # Seed Firestore
        if not args.bigquery_only and not args.pubsub_only:
            print("Seeding Firestore Live Twin...")
            runner = SubprocessRunner()
            token_provider = GcloudTokenProvider(runner)
            transport = HttpTransport(token_provider)
            results["firestore"] = seed_firestore(transport, dry_run, args.force)
            print(f"  Result: {json.dumps(results['firestore'], indent=4)}")
            print()

        # Seed BigQuery
        if not args.firestore_only and not args.pubsub_only:
            print("Seeding BigQuery historical context...")
            results["bigquery"] = seed_bigquery(dry_run)
            print(f"  Result: {json.dumps(results['bigquery'], indent=4)}")
            print()

        # Publish Pub/Sub events
        if args.publish_events or args.pubsub_only:
            print("Publishing demo events to Pub/Sub...")
            events = generate_demo_events()
            results["pubsub"] = publish_events(events, dry_run)
            print(f"  Result: {json.dumps(results['pubsub'], indent=4)}")
            print()

        # Create seed manifest for deterministic reset
        if not dry_run:
            manifest = create_seed_manifest(
                run_id=f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
                counts={
                    "firestore": results.get("firestore", {}).get("seeded", 0),
                    "bigquery": results.get("bigquery", {}).get("inserted", 0),
                    "pubsub": results.get("pubsub", {}).get("published", 0),
                }
            )
            print("Seed manifest created:")
            print(f"  Run ID: {manifest['run_id']}")
            print(f"  Namespace: {manifest['namespace']}")
            print()

        # Summary
        print("=" * 60)
        print("SEED COMPLETE")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Start the API: python -m retailtwin_api")
        print("  2. Open the web UI")
        print("  3. Observe the autonomous workflow triggered by events")
        print()
        print("Demo flow:")
        print("  RESET → Firestore baseline → BigQuery context → Pub/Sub event →")
        print("  Observer → Investigator → Planner → Simulation → KPI → DCG →")
        print("  Live mutation → Verifier → 3D update")
        print()

        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
