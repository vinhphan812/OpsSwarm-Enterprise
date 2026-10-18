#!/usr/bin/env python3
"""Seed Firestore Live Twin with canonical demo baseline.

Issue #135: Seed and reset real GCP data for deterministic end-to-end demo.

This script seeds the Firestore Live Twin with the canonical demo baseline:
- Store: store-001
- Products: 556 SKUs including P001 (foundation) and P017 (demand surge target)
- All inventory documents with version=1

Idempotent: safe to run multiple times. The seed() method uses update semantics.

Usage:
    # Dry run (validate only)
    python infrastructure/gcp/seed_firestore.py --dry-run

    # Seed Firestore
    CONFIRM_SEED=yes python infrastructure/gcp/seed_firestore.py

    # Reset and reseed
    python infrastructure/gcp/seed_firestore.py --reset
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

# Add repo root to path for imports
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# GCP Configuration
PROJECT = os.environ.get("GCP_PROJECT_ID", "retailtwin-ai-511002")
REGION = os.environ.get("GCP_REGION", "us-central1")
CANONICAL_PROJECT = "retailtwin-ai-511002"

# Firestore paths
COLLECTION_STORES = "stores"
STORE_ID = "store-001"
VERSION = "v1"


class CommandRunner(Protocol):
    """Protocol for executing shell commands."""
    def run(self, args: list[str]) -> str: ...


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    env["CLOUDSDK_CORE_PROJECT"] = PROJECT
    return env


class SubprocessRunner:
    """Runs gcloud commands with SDK's authenticated credentials."""
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


class HttpResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body


class HttpTransport:
    """HTTP transport for Firestore REST API."""
    def __init__(self, token_provider: Protocol) -> None:
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
            raise RuntimeError(f"Firestore request failed: {exc.reason}") from exc


class GcloudTokenProvider:
    """Gets access token from gcloud."""
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner
        self._token: str | None = None

    def get_token(self) -> str:
        if self._token is None:
            raw = self._runner.run(["gcloud", "auth", "print-access-token", "--quiet"])
            self._token = raw.strip()
        return self._token


def database_root() -> str:
    return f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


def doc_name(collection: str, *path: str) -> str:
    segments = [collection, *path]
    return f"{database_root()}/{'/'.join(segments)}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


# Firestore rejects a commit with more than 500 writes; the demo store has 556 products.
FIRESTORE_COMMIT_LIMIT = 500


def commit_batches(writes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split writes into commits Firestore accepts. Each batch is atomic; the upserts are idempotent."""
    return [writes[i : i + FIRESTORE_COMMIT_LIMIT] for i in range(0, len(writes), FIRESTORE_COMMIT_LIMIT)]


# Import seed data
from data.seed.demo_seed import DEMO_PRODUCTS, SeedProduct


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
        "updated_at": {"timestampValue": now},
    }


def _store_fields(now: str) -> dict[str, Any]:
    return {
        "store_id": {"stringValue": STORE_ID},
        "version": {"stringValue": VERSION},
        "updated_at": {"timestampValue": now},
    }


class FirestoreSeeder:
    """Seeds the Firestore Live Twin with demo baseline data."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        url = f"{database_root()}/stores"
        try:
            response = self._transport.request("GET", url, None, {"Content-Type": "application/json"})
            self._available = response.status in (200, 404)
        except Exception:
            self._available = False
        return self._available

    def seed(self, products: tuple[SeedProduct, ...], dry_run: bool = False) -> dict[str, Any]:
        """Seed the Live Twin with demo products."""
        if dry_run:
            return self._dry_run(products)

        now = _timestamp()
        writes: list[dict[str, Any]] = []

        # Upsert store metadata
        store_doc = doc_name(COLLECTION_STORES, STORE_ID)
        writes.append({
            "update": {
                "name": store_doc,
                "fields": _store_fields(now),
            }
        })

        # Upsert all inventory documents
        for seed in products:
            inv_doc = doc_name(COLLECTION_STORES, STORE_ID, "inventory", seed.sku)
            writes.append({
                "update": {
                    "name": inv_doc,
                    "fields": _inventory_fields(seed, now),
                }
            })

        url = f"{database_root()}:commit"
        for batch in commit_batches(writes):
            raw = json.dumps({"writes": batch}).encode("utf-8")

            response = self._transport.request("POST", url, raw, {"Content-Type": "application/json"})

            if response.status != 200:
                try:
                    error = json.loads(response.body)
                    raise RuntimeError(f"Seed failed: {error.get('error', {}).get('message', response.body)}")
                except json.JSONDecodeError:
                    raise RuntimeError(f"Seed failed (HTTP {response.status}): {response.body[:200]}")

        return {
            "seeded_products": len(products),
            "store_id": STORE_ID,
            "version": VERSION,
            "timestamp": now,
        }

    def _dry_run(self, products: tuple[SeedProduct, ...]) -> dict[str, Any]:
        """Validate seed data without writing."""
        return {
            "dry_run": True,
            "products_to_seed": len(products),
            "store_id": STORE_ID,
            "version": VERSION,
            "sample": [
                {
                    "sku": p.sku,
                    "shelf_id": p.shelf_id,
                    "slot_id": p.slot_id,
                    "facings": p.facings,
                    "shelf_quantity": p.shelf_quantity,
                    "backroom_quantity": p.backroom_quantity,
                }
                for p in list(products)[:5]  # Show first 5 as sample
            ],
        }

    def reset(self) -> dict[str, Any]:
        """Reset the Live Twin by deleting all inventory documents."""
        # List all inventory documents
        url = f"{database_root()}/stores/{STORE_ID}/inventory"
        response = self._transport.request("GET", url, None, {"Content-Type": "application/json"})

        if response.status == 404:
            return {"reset": True, "deleted": 0, "message": "No inventory found"}

        if response.status != 200:
            raise RuntimeError(f"Failed to list inventory: {response.body[:200]}")

        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError:
            raise RuntimeError("Inventory list response is not JSON")

        documents = payload.get("documents", [])
        if not documents:
            return {"reset": True, "deleted": 0, "message": "No inventory to delete"}

        writes: list[dict[str, Any]] = []
        for doc in documents:
            name = doc.get("name", "")
            if name:
                writes.append({"delete": name})

        # Bump store version
        store_doc = doc_name(COLLECTION_STORES, STORE_ID)
        writes.append({
            "update": {
                "name": store_doc,
                "fields": _store_fields(_timestamp()),
            }
        })

        payload = {"writes": writes}
        url = f"{database_root()}:commit"
        raw = json.dumps(payload).encode("utf-8")

        response = self._transport.request("POST", url, raw, {"Content-Type": "application/json"})

        if response.status != 200:
            raise RuntimeError(f"Reset failed (HTTP {response.status}): {response.body[:200]}")

        return {"reset": True, "deleted": len(documents)}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def check_guardrails() -> None:
    """Validate environment before seeding."""
    if PROJECT != CANONICAL_PROJECT:
        die(f"Refusing project {PROJECT}. Seed applies only to {CANONICAL_PROJECT}.")

    if os.environ.get("CONFIRM_SEED", "") != "yes" and os.environ.get("CONFIRM_SEED", "") != "dry":
        die("Set CONFIRM_SEED=yes to seed, or CONFIRM_SEED=dry to validate without writing.")

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
        description="Seed Firestore Live Twin with canonical demo baseline."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate seed data without writing to Firestore"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the Live Twin (delete all inventory) before seeding"
    )
    args = parser.parse_args()

    # Determine mode
    confirm = os.environ.get("CONFIRM_SEED", "")
    dry_run = args.dry_run or confirm == "dry"

    print(f"Project:    {PROJECT}")
    print(f"Region:     {REGION}")
    print(f"Store:      {STORE_ID}")
    print(f"Dry run:    {dry_run}")
    print(f"Reset:     {args.reset}")
    print(f"Products:   {len(DEMO_PRODUCTS)}")
    print()

    if not dry_run:
        check_guardrails()
    else:
        print("DRY RUN MODE - No changes will be made")
        print()

    # Initialize components
    runner = SubprocessRunner()
    token_provider = GcloudTokenProvider(runner)
    transport = HttpTransport(token_provider)
    seeder = FirestoreSeeder(transport)

    # Check availability
    if not seeder.is_available():
        die("Firestore is not available. Check credentials and project.")

    print("Firestore is available")

    try:
        if args.reset:
            print("Resetting Live Twin...")
            result = seeder.reset()
            print(f"Reset complete: {json.dumps(result, indent=2)}")
            print()

        if not args.reset and not dry_run:
            print("Skipping seed (use without --reset to seed)")
            return 0

        print(f"Seeding Live Twin with {len(DEMO_PRODUCTS)} products...")
        result = seeder.seed(DEMO_PRODUCTS, dry_run=dry_run)
        print(f"Seed complete: {json.dumps(result, indent=2)}")

        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
