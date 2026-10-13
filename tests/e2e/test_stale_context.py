"""
test_stale_context.py

Tests for stale-context detection and rejection.

Covered scenarios:
  G04 stale-context gate (planned):
    - A decision built against an older context version is REFRESH_REQUIRED
    - No live mutation is possible with stale context_version
    - Version bump on Live Twin invalidates prior decisions

Current status:
    The store fixture is read-only and has a fixed context_version. The
    guard-level stale test runs the real Decision Context Guard and
    No-Stale-Commit (#16, #17) against an in-memory Live Twin. Executor
    rejection of a stale commit is #18.

Key DCG invariants that must hold in the full implementation:
    1. context_version in Decision must match current store context_version
    2. A decision with an outdated context_version is DENY / REFRESH_REQUIRED
    3. Live Twin mutation endpoint must reject stale-authorized requests
    4. event_id correlation enables stale-context trace across the control loop
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import make_event


class TestContextVersionReporting:
    """Store API surfaces context_version for DCG to read."""

    def test_store_reports_context_version(self, client: TestClient) -> None:
        response = client.get("/store")
        assert response.status_code == 200
        body = response.json()
        assert "context_version" in body
        assert body["context_version"].startswith("store-001:")
        assert body["store_id"] == "store-001"

    def test_inventory_reports_version(self, client: TestClient) -> None:
        response = client.get("/inventory/P001")
        assert response.status_code == 200
        body = response.json()
        assert "version" in body
        assert isinstance(body["version"], int)
        assert body["version"] >= 1

    def test_inventory_version_matches_store_version(
        self, client: TestClient
    ) -> None:
        """All products share the same store context_version string prefix.

        Note: the store-level context_version string and the per-product
        integer version field are separate concepts.  The string tracks
        decision context epochs; the integer tracks executor commit count.
        This test verifies prefix consistency; commit-count comparison
        belongs in executor commit tests.
        """
        store_resp = client.get("/store")
        assert store_resp.status_code == 200
        store_ctx = store_resp.json()["context_version"]
        # Prefix must be consistent (store_id prefix, then colon + epoch)
        assert store_ctx.startswith("store-001:")
        for sku in ("P001",):
            inv_resp = client.get(f"/inventory/{sku}")
            if inv_resp.status_code == 404:
                continue
            assert inv_resp.status_code == 200
            # Integer version field is independent of the store-level
            # context_version string; no direct comparison is valid.
            assert isinstance(inv_resp.json()["version"], int)

    def test_context_version_is_stable_without_mutation(self, client: TestClient) -> None:
        """Without Executor, context_version and inventory version cannot change."""
        first_store = client.get("/store").json()
        first_inv = client.get("/inventory/P001").json()

        client.post("/events", json=make_event())
        client.post("/events", json=make_event())

        second_store = client.get("/store").json()
        second_inv = client.get("/inventory/P001").json()

        assert first_store["context_version"] == second_store["context_version"]
        assert first_inv["version"] == second_inv["version"]


class TestEventCorrelationForStaleTrace:
    """Event correlation IDs link evidence to decisions for stale-context trace."""

    def test_event_carries_correlation_id(self, client: TestClient) -> None:
        payload = make_event(correlation_id="run-stale-001")
        response = client.post("/events", json=payload)
        assert response.status_code == 201
        assert response.json()["event"]["correlation_id"] == "run-stale-001"

    def test_duplicate_preserves_original_correlation_id(
        self, client: TestClient
    ) -> None:
        payload = make_event(correlation_id="run-stale-dup")
        first = client.post("/events", json=payload).json()
        second = client.post("/events", json=payload).json()
        assert first["event"]["correlation_id"] == second["event"]["correlation_id"]

    def test_event_receipt_preserves_event_id(self, client: TestClient) -> None:
        payload = make_event(event_id="smoke-evt-corr-001")
        response = client.post("/events", json=payload)
        assert response.status_code == 201
        body = response.json()
        assert body["event"]["event_id"] == "smoke-evt-corr-001"
        # Verify idempotent fetch
        again = client.post("/events", json=payload).json()
        assert again["event"]["event_id"] == "smoke-evt-corr-001"


class TestStaleContextContract:
    """
    Documented contracts that DCG and Executor must enforce once live.

    These tests pass today because there is no live mutation endpoint, but
    they serve as the acceptance criteria for the DCG implementation.
    """

    def test_no_mutation_endpoint_exists_at_day0(self, client: TestClient) -> None:
        """
        At day-0, POST /events does NOT mutate Live Twin.
        This is the core G04 isolation contract.
        """
        before = client.get("/inventory/P001").json()
        client.post("/events", json=make_event(quantity=99))
        after = client.get("/inventory/P001").json()
        assert after["shelf_quantity"] == before["shelf_quantity"]
        assert after["version"] == before["version"]

    def test_guard_health_endpoint_reports_fixture_status(
        self, client: TestClient
    ) -> None:
        """Health endpoint is the API availability preflight at day-0."""
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ("ok", "degraded")
        assert body["fixture_loaded"] is True
        assert body["store_id"] == "store-001"

    def test_stale_context_is_rejected_by_dcg(self) -> None:
        """
        G04 at the guard boundary (#17).

          1. D1 is built while P001 is at version N.
          2. P001 moves to N+1 on the Live Twin.
          3. D1 is submitted: REFRESH_REQUIRED, no commit binding, Live unchanged,
             and the audit says why.
        """
        from datetime import datetime, timezone

        from retailtwin_api.contracts import (
            DCGVerdict, Decision, EvidenceBundle, ExpectedImpact, ReplenishShelf,
        )
        from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventorySeed
        from retailtwin_api.guard.decision_context_guard import (
            VERSION_STALE, DecisionContextGuard, InMemoryGuardAudit, NoStaleCommit,
        )

        now = datetime.now(timezone.utc)
        twin = InMemoryTwinRepository()
        twin.seed("store-001", "v1", [InventorySeed(
            sku="P001", shelf_id="SH1", slot_id="S1", facings=2, shelf_quantity=10, backroom_quantity=30,
        )])
        d1 = Decision(
            decision_id="d1", agent_id="planner", context_version="store-001:v1", context_timestamp=now,
            evidence=[EvidenceBundle(
                bundle_id="b1", provenance="tool-registry", source="investigator",
                entity_versions={"P001": "1"}, collected_at=now, freshness=now,
                store_id="store-001", correlation_id="run-stale-g04", is_sufficient=True,
            )],
            proposed_actions=[ReplenishShelf(sku="P001", quantity=6)],
            expected_impact=ExpectedImpact(kpi_score=0.2, description="restock"),
        )
        current = twin.get_inventory("store-001", "P001")
        assert current is not None
        twin.upsert_inventory(current.model_copy(update={"version": 2}), expected_version=1)
        before = twin.get_inventory("store-001", "P001")

        audit = InMemoryGuardAudit()
        result, binding = NoStaleCommit(DecisionContextGuard(twin), audit).authorize(d1)

        assert (result.verdict, result.reason_code) == (DCGVerdict.REFRESH_REQUIRED, VERSION_STALE)
        assert binding is None
        assert twin.get_inventory("store-001", "P001") == before
        assert [(e.correlation_id, e.reason_code) for e in audit.events("d1")] == [("run-stale-g04", VERSION_STALE)]
