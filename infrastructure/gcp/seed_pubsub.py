#!/usr/bin/env python3
"""Publish demand-surge events through Pub/Sub for the demo scenario.

Issue #135: Seed and reset real GCP data for deterministic end-to-end demo.

This script publishes the Weekend Demand Surge event series through the
real store-events Pub/Sub topic, triggering the autonomous workflow:
- Friday baseline: 50 units in 4 hours (12.5/hour)
- Saturday surge: 73 units in 4 hours (18.25/hour)
- Increase: 46%

The events travel through the full backbone:
Pub/Sub -> Observer -> Investigator -> Planner -> Simulation -> DCG -> Executor

Usage:
    # Preview events without publishing
    python infrastructure/gcp/seed_pubsub.py --dry-run

    # Publish events
    CONFIRM_SEED=yes python infrastructure/gcp/seed_pubsub.py

    # Publish only baseline (before surge)
    python infrastructure/gcp/seed_pubsub.py --phase=baseline

    # Publish only surge events
    python infrastructure/gcp/seed_pubsub.py --phase=surge
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
TOPIC = os.environ.get("STORE_EVENTS_TOPIC", "store-events")
CANONICAL_PROJECT = "retailtwin-ai-511002"

STORE_ID = "store-001"
SKU = "P017"  # Demand surge target
SOURCE = "synthetic-pos"
DEMO_NAMESPACE = "retailtwin-demo"
CORRELATION_ID = f"{DEMO_NAMESPACE}-run-weekend-demand-surge-1"


def demo_event_id(suffix: str) -> str:
    """Return a deterministic event ID that reset_demo.py can safely own."""
    return f"{DEMO_NAMESPACE}-{suffix}"

# Event timing (from data/synthetic/weekend-demand-surge.json)
BASELINE_START = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
SURGE_START = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
WINDOW_HOURS = 4


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB"] = "https://us-central1-pubsub.googleapis.com/"
    return env


def canonical_body(event: dict[str, Any]) -> str:
    """Create canonical JSON body for the event."""
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


def message_attributes(event: dict[str, Any]) -> dict[str, str]:
    """Create Pub/Sub message attributes."""
    return {
        "correlation_id": event["correlation_id"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "store_id": event["store_id"],
    }


def publish_event(event: dict[str, Any]) -> dict[str, Any]:
    """Publish one event to the store-events topic."""
    body = canonical_body(event)
    attrs = message_attributes(event)

    args = [
        "gcloud", "pubsub", "topics", "publish", TOPIC,
        "--project", PROJECT,
        "--quiet",
        f"--message={body}",
    ]
    for key, value in attrs.items():
        args.append(f"--attribute={key}={value}")

    completed = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env=command_env(),
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"Publish failed: {completed.stderr or completed.stdout or 'unknown error'}"
        )

    return {"published": event["event_id"], "message_id": completed.stdout.strip()}


def generate_baseline_events() -> list[dict[str, Any]]:
    """Generate Friday baseline events (50 units in 4 hours)."""
    events = []
    quantities = (10, 10, 10, 10, 10)  # 5 events = 50 units
    step = timedelta(hours=WINDOW_HOURS) / len(quantities)

    for index, quantity in enumerate(quantities, start=1):
        event = {
            "event_id": demo_event_id(f"evt-p017-base-{index:04d}"),
            "correlation_id": CORRELATION_ID,
            "event_type": "sale.completed",
            "store_id": STORE_ID,
            "sku": SKU,
            "quantity": quantity,
            "occurred_at": (BASELINE_START + step * (index - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": SOURCE,
        }
        events.append(event)

    return events


def generate_surge_events() -> list[dict[str, Any]]:
    """Generate Saturday surge events (73 units in 4 hours)."""
    events = []
    quantities = (9, 9, 9, 9, 9, 9, 9, 10)  # 8 events = 73 units
    step = timedelta(hours=WINDOW_HOURS) / len(quantities)

    for index, quantity in enumerate(quantities, start=1):
        event = {
            "event_id": demo_event_id(f"evt-p017-surge-{index:04d}"),
            "correlation_id": CORRELATION_ID,
            "event_type": "sale.completed",
            "store_id": STORE_ID,
            "sku": SKU,
            "quantity": quantity,
            "occurred_at": (SURGE_START + step * (index - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": SOURCE,
        }
        events.append(event)

    return events


def get_all_events() -> list[dict[str, Any]]:
    """Get all demo events (baseline + surge)."""
    return generate_baseline_events() + generate_surge_events()


def publish_events(
    events: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish a list of events to Pub/Sub."""
    if dry_run:
        return {
            "dry_run": True,
            "events_to_publish": len(events),
            "sample": events[:3],
        }

    results = {"published": [], "errors": []}

    for event in events:
        try:
            result = publish_event(event)
            results["published"].append(result)
            print(f"  Published: {event['event_id']}")
        except Exception as e:
            results["errors"].append({"event_id": event["event_id"], "error": str(e)})
            print(f"  Error: {event['event_id']}: {e}", file=sys.stderr)

    return results


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_guardrails() -> None:
    """Validate environment before publishing."""
    if PROJECT != CANONICAL_PROJECT:
        die(f"Refusing project {PROJECT}. Events stay on {CANONICAL_PROJECT}.")

    if os.environ.get("CONFIRM_SEED", "") not in ("yes", "dry"):
        die("Set CONFIRM_SEED=yes to publish, or CONFIRM_SEED=dry to preview.")

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
        description="Publish demand-surge events through Pub/Sub."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview events without publishing"
    )
    parser.add_argument(
        "--phase",
        choices=["all", "baseline", "surge"],
        default="all",
        help="Which phase of events to publish (default: all)"
    )
    args = parser.parse_args()

    confirm = os.environ.get("CONFIRM_SEED", "")
    dry_run = args.dry_run or confirm == "dry"

    print(f"Project:       {PROJECT}")
    print(f"Topic:         {TOPIC}")
    print(f"Correlation:   {CORRELATION_ID}")
    print(f"SKU:           {SKU}")
    print(f"Phase:         {args.phase}")
    print(f"Dry run:       {dry_run}")
    print()

    if not dry_run:
        check_guardrails()
    else:
        print("DRY RUN MODE - No events will be published")
        print()

    # Get events for the selected phase
    if args.phase == "baseline":
        events = generate_baseline_events()
    elif args.phase == "surge":
        events = generate_surge_events()
    else:
        events = get_all_events()

    print(f"Events to publish: {len(events)}")
    print()

    # Show event summary
    print("Event summary:")
    print(f"  Baseline (Friday): {len(generate_baseline_events())} events, "
          f"{sum(e['quantity'] for e in generate_baseline_events())} units")
    print(f"  Surge (Saturday): {len(generate_surge_events())} events, "
          f"{sum(e['quantity'] for e in generate_surge_events())} units")
    print(f"  Total: {len(events)} events, "
          f"{sum(e['quantity'] for e in events)} units")
    print(f"  Increase: 46% (73/50 - 1)")
    print()

    if dry_run:
        print("Events to publish:")
        for event in events:
            print(f"  {event['event_id']}: {event['sku']} x{event['quantity']} "
                  f"at {event['occurred_at']}")
        print()
        print("Run without --dry-run to publish the events.")
        return 0

    try:
        print("Publishing events...")
        result = publish_events(events, dry_run=False)
        print()

        if result["errors"]:
            print(f"Errors: {len(result['errors'])}")
            return 1

        print(f"Published: {len(result['published'])} events")
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
