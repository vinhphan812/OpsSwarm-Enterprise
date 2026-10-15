"""No-GCP-mutation safety tests for demo reset and seed scripts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reset_demo = load_module("reset_demo_under_test", "infrastructure/gcp/reset_demo.py")
seed_gcp = load_module("seed_gcp_under_test", "infrastructure/gcp/seed_gcp.py")
seed_bigquery = load_module("seed_bigquery_under_test", "infrastructure/gcp/seed_bigquery.py")


class FakeFirestore:
    """In-memory Firestore REST fixture; never contacts GCP.

    Inventory documents are stored as full Firestore document dicts so that
    is_demo_seed_inventory() can inspect the fields without needing a live
    Firestore API call.
    """

    def __init__(self) -> None:
        root = reset_demo.database_root()
        # Each inventory entry is a full Firestore document dict.
        # demo-seeded docs have demo_seed_version; others don't.
        self.inventory: list[dict[str, Any]] = [
            {
                "name": f"{root}/stores/store-001/inventory/P017",
                "fields": {
                    "store_id": {"stringValue": "store-001"},
                    "sku": {"stringValue": "P017"},
                    "demo_seed_version": {"stringValue": reset_demo.DEMO_SEED_VERSION},
                },
            },
        ]
        self.claims = {
            f"{root}/store_event_claims/retailtwin-demo-evt-p017-base-0001",
            f"{root}/store_event_claims/retailtwin-demo-evt-p017-surge-0001",
            f"{root}/store_event_claims/production-event-0001",
        }
        self.commits: list[dict[str, Any]] = []

    def request(
        self, method: str, url: str, payload: bytes | None, headers: dict[str, str]
    ) -> Any:
        assert headers["Content-Type"] == "application/json"
        root = reset_demo.database_root()
        if method == "GET" and url == f"{root}/stores/store-001/inventory":
            return reset_demo.HttpResponse(
                200, json.dumps({"documents": self.inventory})
            )
        if method == "GET" and url.startswith(f"{root}/store_event_claims?"):
            return reset_demo.HttpResponse(
                200, json.dumps({"documents": [{"name": name} for name in self.claims]})
            )
        if method == "POST" and url == f"{root}:commit":
            assert payload is not None
            commit = json.loads(payload)
            self.commits.append(commit)
            for write in commit["writes"]:
                deleted = write.get("delete")
                if deleted:
                    self.claims.discard(deleted)
                    self.inventory = [
                        doc for doc in self.inventory if doc.get("name") != deleted
                    ]
            return reset_demo.HttpResponse(200, json.dumps({"writeResults": [{}]}))
        raise AssertionError(f"Unexpected request: {method} {url}")


def test_reset_firestore_deletes_only_demo_claims_and_replay_is_fresh() -> None:
    transport = FakeFirestore()

    first = reset_demo.reset_firestore(transport)
    assert first["firestore"]["demo_claims_deleted"] == 2
    assert transport.claims == {next(name for name in transport.claims if name.endswith("production-event-0001"))}
    deleted = {write["delete"] for write in transport.commits[0]["writes"] if "delete" in write}
    # P017 is demo-seeded (demo_seed_version=v1) so it IS eligible for deletion.
    assert all("retailtwin-demo-" in name or "/inventory/" in name for name in deleted)
    assert not any("production-event-0001" in name for name in deleted)

    # The repeated reset is safe and proves the deterministic demo IDs are no
    # longer held by stale Firestore claims before a reseed/replay.
    second = reset_demo.reset_firestore(transport)
    assert second["firestore"]["demo_claims_deleted"] == 0
    assert len(transport.commits) == 2


def test_reset_firestore_dry_run_has_no_mutation_and_exposes_bounded_scope() -> None:
    transport = FakeFirestore()
    result = reset_demo.reset_firestore(transport, dry_run=True)

    assert result["firestore"]["claim_scope"] == "store_event_claims/retailtwin-demo-*"
    assert transport.commits == []
    assert any(name.endswith("production-event-0001") for name in transport.claims)


def test_reset_firestore_preserves_non_demo_inventory() -> None:
    """Negative test: non-demo inventory (no demo_seed_version) is NOT deleted.

    A document without demo_seed_version is treated as live/production state and
    must survive a reset.  This is the core safety fix for issue #135.
    """
    root = reset_demo.database_root()
    # Live inventory document — no demo_seed_version field, simulating production
    # state created by the live-twin system after seeding.
    LIVE_SKU = "LIVE-P001"
    fake = FakeFirestore()
    fake.inventory.append({
        "name": f"{root}/stores/store-001/inventory/{LIVE_SKU}",
        "fields": {
            "store_id": {"stringValue": "store-001"},
            "sku": {"stringValue": LIVE_SKU},
            # intentionally missing demo_seed_version
            "shelf_quantity": {"integerValue": "50"},
        },
    })

    result = reset_demo.reset_firestore(fake)

    # Reset should report the demo-seeded P017 as deleted.
    assert result["firestore"]["inventory_deleted"] == 1

    # Live document must be preserved.
    assert result["firestore"]["non_demo_inventory_preserved"] == 1
    assert any(doc["name"].endswith(f"/{LIVE_SKU}") for doc in fake.inventory)

    # The live document must NOT appear in any delete write.
    all_deleted = set()
    for commit in fake.commits:
        for write in commit.get("writes", []):
            if "delete" in write:
                all_deleted.add(write["delete"])
    assert not any(LIVE_SKU in name for name in all_deleted)


def test_seed_gcp_partial_bigquery_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    events = seed_gcp.generate_p017_context()[:3]
    calls: list[list[str]] = []

    def fail_second_call(args: list[str]) -> str:
        calls.append(args)
        if len(calls) == 2:
            raise RuntimeError("simulated bq outage")
        return "[]"

    monkeypatch.setattr(seed_gcp, "generate_p017_context", lambda: events)
    monkeypatch.setattr(seed_gcp, "run_bq", fail_second_call)

    with pytest.raises(RuntimeError, match=r"BigQuery seed failed after 1/3 event\(s\).*failed event_id="):
        seed_gcp.seed_bigquery()
    assert len(calls) == 2


def test_standalone_bigquery_seed_partial_failure_is_not_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [{"event_id": "retailtwin-demo-one"}, {"event_id": "retailtwin-demo-two"}]
    calls = 0

    def insert(event: dict[str, Any], dry_run: bool = False) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated bq outage")
        return {"inserted": event["event_id"]}

    monkeypatch.setattr(seed_bigquery, "insert_sales_event", insert)

    with pytest.raises(RuntimeError, match=r"BigQuery seed failed after 1/2 event\(s\)"):
        seed_bigquery.seed_table("sales_events", events)
