#!/usr/bin/env python3
"""Seed BigQuery with historical sales/inventory context for the demo.

Issue #135: Seed and reset real GCP data for deterministic end-to-end demo.

This script seeds BigQuery with historical sales data that provides context
for the AI's demand forecasting and KPI calculations:
- sales_events: Historical POS transactions (4 weeks prior to demo)
- inventory_events: Historical inventory movements
- agent_actions: Empty audit trail for demo (baseline)

Idempotent: uses NOT EXISTS to avoid duplicates. Safe to run multiple times.

Usage:
    # Dry run (validate only)
    python infrastructure/gcp/seed_bigquery.py --dry-run

    # Seed BigQuery
    CONFIRM_SEED=yes python infrastructure/gcp/seed_bigquery.py

    # Reset and reseed
    python infrastructure/gcp/seed_bigquery.py --reset
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# GCP Configuration
PROJECT = os.environ.get("GCP_PROJECT_ID", "retailtwin-ai-511002")
REGION = os.environ.get("GCP_REGION", "us-central1")
DATASET = os.environ.get("BIGQUERY_DATASET", "retailtwin")
CANONICAL_PROJECT = "retailtwin-ai-511002"

STORE_ID = "store-001"


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_CORE_PROJECT"] = PROJECT
    return env


def bq_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    return env


def run_bq(args: list[str]) -> str:
    """Run a bq command and return stdout."""
    cmd = ["bq", "--quiet", f"--project_id={PROJECT}", f"--location={REGION}"] + args
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=bq_env(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"bq command failed with exit {completed.returncode}.")
    return completed.stdout


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_guardrails() -> None:
    """Validate environment before seeding."""
    if PROJECT != CANONICAL_PROJECT:
        die(f"Refusing project {PROJECT}. Seed applies only to {CANONICAL_PROJECT}.")

    if os.environ.get("CONFIRM_SEED", "") not in ("yes", "dry"):
        die("Set CONFIRM_SEED=yes to seed, or CONFIRM_SEED=dry to validate without writing.")


def qualified_table(table: str) -> str:
    return f"`{PROJECT}.{DATASET}.{table}`"


def format_timestamp(dt: datetime) -> str:
    """Format datetime for BigQuery TIMESTAMP."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Demo namespace prefix for all demo data
DEMO_NAMESPACE = "retailtwin-demo"

def demo_event_id(suffix: str) -> str:
    """Create a deterministic event ID with demo namespace."""
    return f"{DEMO_NAMESPACE}-{suffix}"


# Historical sales data generator (deterministic)
def generate_historical_sales(
    sku: str,
    start_date: datetime,
    days: int,
    avg_daily_units: int,
    correlation_prefix: str,
) -> list[dict[str, Any]]:
    """Generate deterministic historical sales for a SKU."""
    events = []
    current = start_date

    for day in range(days):
        # Daily pattern: higher on weekends
        is_weekend = current.weekday() >= 5
        multiplier = 1.5 if is_weekend else 1.0

        # Add some variation based on day
        daily_units = int(avg_daily_units * multiplier * (0.9 + 0.2 * ((day % 7) / 7)))

        # Generate hourly events (simplified - aggregate into single event per 4 hours)
        for hour_offset in [0, 4, 8, 12, 16, 20]:
            if daily_units > 0:
                event_time = current + timedelta(hours=hour_offset)
                # Each event represents a batch sale
                quantity = max(1, daily_units // 6 + (1 if day % 3 == 0 else 0))
                events.append({
                    "event_id": demo_event_id(f"hist-{sku.lower()}-{current.strftime('%Y%m%d')}-{hour_offset:02d}"),
                    "correlation_id": demo_event_id(f"{correlation_prefix}-{current.strftime('%Y%m%d')}"),
                    "event_type": "sale.completed",
                    "store_id": STORE_ID,
                    "sku": sku,
                    "quantity": quantity,
                    "occurred_at": format_timestamp(event_time),
                    "source": "historical-pos",
                    "run_id": "",  # Will be filled by seed_gcp.py
                })
        current += timedelta(days=1)

    return events


def generate_p017_context() -> list[dict[str, Any]]:
    """Generate P017 historical context - matches the weekend demand surge pattern."""
    # P017 shows consistent Friday-Sunday surge pattern in history
    events = []
    base_date = datetime(2026, 9, 12, tzinfo=timezone.utc)  # Start 4 weeks back

    for week in range(4):  # 4 weeks of history
        week_start = base_date + timedelta(weeks=week)

        # Friday 8am-12pm: 40-50 units
        for i, hour in enumerate([8, 9, 10, 11]):
            events.append({
                "event_id": demo_event_id(f"hist-p017-week{week}-fri-{hour}"),
                "correlation_id": demo_event_id(f"hist-week{week}"),
                "event_type": "sale.completed",
                "store_id": STORE_ID,
                "sku": "P017",
                "quantity": 10 + (i % 2) * 2,  # 10-12 units per hour
                "occurred_at": format_timestamp(week_start + timedelta(hours=hour)),
                "source": "historical-pos",
                "run_id": "",
            })

        # Saturday 8am-12pm: 55-73 units (surge)
        for i, hour in enumerate([8, 9, 10, 11, 12]):
            events.append({
                "event_id": demo_event_id(f"hist-p017-week{week}-sat-{hour}"),
                "correlation_id": demo_event_id(f"hist-week{week}"),
                "event_type": "sale.completed",
                "store_id": STORE_ID,
                "sku": "P017",
                "quantity": 11 + (i % 3) * 2,  # 11-15 units per hour = 55-73 total
                "occurred_at": format_timestamp(week_start + timedelta(days=1, hours=hour)),
                "source": "historical-pos",
                "run_id": "",
            })

        # Sunday 8am-12pm: 30-40 units
        for i, hour in enumerate([8, 9, 10, 11]):
            events.append({
                "event_id": demo_event_id(f"hist-p017-week{week}-sun-{hour}"),
                "correlation_id": demo_event_id(f"hist-week{week}"),
                "event_type": "sale.completed",
                "store_id": STORE_ID,
                "sku": "P017",
                "quantity": 8 + (i % 2) * 2,  # 8-10 units per hour
                "occurred_at": format_timestamp(week_start + timedelta(days=2, hours=hour)),
                "source": "historical-pos",
                "run_id": "",
            })

        # Weekday baseline: ~25 units per day
        for day_offset, day_name in [(3, "mon"), (4, "tue"), (5, "wed")]:
            events.append({
                "event_id": demo_event_id(f"hist-p017-week{week}-{day_name}"),
                "correlation_id": demo_event_id(f"hist-week{week}"),
                "event_type": "sale.completed",
                "store_id": STORE_ID,
                "sku": "P017",
                "quantity": 8 + (day_offset % 3) * 2,  # 8-10 units per event
                "occurred_at": format_timestamp(week_start + timedelta(days=day_offset, hours=10)),
                "source": "historical-pos",
                "run_id": "",
            })

    return events


def get_all_sales_events() -> list[dict[str, Any]]:
    """Generate all historical sales events."""
    events = []

    # P017 historical context (shows surge pattern)
    events.extend(generate_p017_context())

    # P001 baseline (consistent sales)
    events.extend(generate_historical_sales(
        sku="P001",
        start_date=datetime(2026, 9, 12, tzinfo=timezone.utc),
        days=28,
        avg_daily_units=12,
        correlation_prefix="hist-p001",
    ))

    # Other key products
    for sku, avg_units in [("P002", 8), ("P003", 5), ("P005", 10), ("P012", 15)]:
        events.extend(generate_historical_sales(
            sku=sku,
            start_date=datetime(2026, 9, 12, tzinfo=timezone.utc),
            days=28,
            avg_daily_units=avg_units,
            correlation_prefix=f"hist-{sku.lower()}",
        ))

    return events


def check_table_exists(table: str) -> bool:
    """Check if BigQuery table exists."""
    try:
        run_bq(["show", "--format=prettyjson", f"{PROJECT}:{DATASET}.{table}"])
        return True
    except RuntimeError:
        return False


def insert_sales_event(event: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """Insert a single sales event using NOT EXISTS pattern."""
    table = qualified_table("sales_events")

    sql = f"""
        INSERT INTO {table}
        (event_id, correlation_id, event_type, store_id, sku, quantity, occurred_at, source, ingested_at)
        SELECT
            @event_id, @correlation_id, @event_type, @store_id, @sku, @quantity,
            @occurred_at, @source, CURRENT_TIMESTAMP()
        FROM (SELECT 1)
        WHERE NOT EXISTS (
            SELECT 1 FROM {table} WHERE event_id = @event_id
        )
    """

    if dry_run:
        return {"dry_run": True, "event_id": event["event_id"]}

    args = [
        "query", "--nouse_legacy_sql", "--format=json",
        "--parameter=event_id:STRING:" + event["event_id"],
        "--parameter=correlation_id:STRING:" + event["correlation_id"],
        "--parameter=event_type:STRING:" + event["event_type"],
        "--parameter=store_id:STRING:" + event["store_id"],
        "--parameter=sku:STRING:" + event["sku"],
        f"--parameter=quantity:INT64:{event['quantity']}",
        "--parameter=occurred_at:TIMESTAMP:" + event["occurred_at"],
        "--parameter=source:STRING:" + event["source"],
        "--maximum_bytes_billed=100000000",
        sql,
    ]

    run_bq(args)
    return {"inserted": event["event_id"]}


def seed_table(
    table: str,
    events: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Seed a BigQuery table with events."""
    if not events:
        return {"table": table, "inserted": 0, "skipped": 0}

    if dry_run:
        return {
            "table": table,
            "dry_run": True,
            "events_to_insert": len(events),
            "sample": events[:3],
        }

    inserted = 0

    for event in events:
        try:
            insert_sales_event(event, dry_run=False)
        except Exception as exc:
            # A failed DML command is never proof that a deterministic event
            # already exists.  Fail closed so callers do not report partial
            # data as a successful/skipped seed.
            raise RuntimeError(
                "BigQuery seed failed after "
                f"{inserted}/{len(events)} event(s); failed event_id={event['event_id']}. "
                "Reset the demo namespace before retrying."
            ) from exc
        inserted += 1

    return {"table": table, "inserted": inserted, "expected": len(events)}


def seed_bigquery(dry_run: bool = False, reset: bool = False) -> dict[str, Any]:
    """Seed BigQuery with historical data."""
    results = {}

    # Check tables exist
    required_tables = ["sales_events", "inventory_events", "agent_actions"]
    for table in required_tables:
        if not check_table_exists(table):
            raise RuntimeError(
                f"Table {table} does not exist. "
                "Run infrastructure/gcp/apply-store-events.sh first."
            )

    # Generate sales events
    sales_events = get_all_sales_events()
    results["sales_events"] = seed_table("sales_events", sales_events, dry_run)

    # Note: inventory_events and agent_actions are typically empty at baseline
    # They are populated by the event backbone and agent actions during demo runs

    return results


def reset_bigquery() -> dict[str, Any]:
    """Reset BigQuery tables by deleting demo-related events."""
    # For BigQuery, we don't delete rows (they're historical)
    # Instead, we document that the tables should be queried with date filters

    return {
        "reset": True,
        "message": "BigQuery tables retain historical data.",
        "note": "Query sales_events with date filters to get demo-only data.",
        "demo_date_filter": "occurred_at >= '2026-10-09T00:00:00Z'",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed BigQuery with historical sales/inventory context."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate seed data without writing to BigQuery"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset demo data (BigQuery retains history)"
    )
    args = parser.parse_args()

    confirm = os.environ.get("CONFIRM_SEED", "")
    dry_run = args.dry_run or confirm == "dry"

    print(f"Project:   {PROJECT}")
    print(f"Dataset:   {DATASET}")
    print(f"Dry run:   {dry_run}")
    print()

    if not dry_run:
        check_guardrails()
    else:
        print("DRY RUN MODE - No changes will be made")
        print()

    # Generate event summary
    sales_events = get_all_sales_events()
    print(f"Sales events to seed: {len(sales_events)}")
    print()

    # Sample events
    print("Sample events:")
    for event in sales_events[:5]:
        print(f"  {event['event_id']}: {event['sku']} x{event['quantity']} at {event['occurred_at']}")
    print("...")

    if dry_run:
        print()
        print("Run without --dry-run to seed the data.")
        return 0

    try:
        if args.reset:
            print("Resetting BigQuery demo data...")
            result = reset_bigquery()
            print(f"Reset: {json.dumps(result, indent=2)}")
            print()

        print("Seeding BigQuery...")
        result = seed_bigquery(dry_run=False, reset=False)
        print(f"Seed complete: {json.dumps(result, indent=2)}")

        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
