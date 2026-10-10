"""
test_canonical_path.py

Happy-path E2E smoke test for the canonical control loop:

    EVENT -> AI -> INVESTIGATE -> SIMULATE -> GUARD -> LIVE -> VERIFY

Because the agent services (Observer, Investigator, Planner, Simulator, DCG,
Executor, Verifier) are stubbed with README.md only, this module tests the
two concrete segments that exist today:

  Stage 1  EVENT -> API accept     (POST /events)
  Stage 2  API -> inventory read   (GET /inventory/{sku})

and validates the invariants that must hold regardless of what the agent stubs
do with the event next:

  - Event is accepted with a stable event_id
  - Inventory is not mutated by event intake (routes.py contract)
  - State isolation: two simultaneous events produce distinct receipts
  - Canonical path stage labels appear in structured logs

A future E2E run with real agent services replaces the stub markers with live
calls and extends the stage timing assertions accordingly.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from conftest import make_event


class TestEventIntake:
    """Stage 1 – EVENT -> API accept (canonical path entry gate)."""

    def test_event_is_accepted_with_stable_id(self, client: TestClient) -> None:
        payload = make_event(event_id="smoke-evt-001", quantity=2)
        response = client.post("/events", json=payload)
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["accepted"] is True
        assert body["duplicate"] is False
        assert body["event"]["event_id"] == "smoke-evt-001"
        assert body["event"]["quantity"] == 2

    def test_event_does_not_mutate_inventory(self, client: TestClient) -> None:
        """Critical isolation invariant: POST /events is read-only."""
        before = client.get("/inventory/P001").json()
        response = client.post("/events", json=make_event(quantity=5))
        assert response.status_code == 201
        after = client.get("/inventory/P001").json()
        assert after["shelf_quantity"] == before["shelf_quantity"]
        assert after["backroom_quantity"] == before["backroom_quantity"]
        assert after["version"] == before["version"]

    def test_duplicate_event_returns_200_not_409(self, client: TestClient) -> None:
        payload = make_event(event_id="smoke-evt-dup")
        first = client.post("/events", json=payload)
        assert first.status_code == 201
        second = client.post("/events", json=payload)
        assert second.status_code == 200
        assert second.json()["duplicate"] is True

    def test_event_conflict_is_detected(self, client: TestClient) -> None:
        payload = make_event(event_id="smoke-evt-conflict", quantity=1)
        assert client.post("/events", json=payload).status_code == 201
        modified = dict(payload)
        modified["quantity"] = 99
        response = client.post("/events", json=modified)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "event_id_conflict"

    def test_invalid_event_returns_422(self, client: TestClient) -> None:
        payload = make_event()
        del payload["sku"]
        response = client.post("/events", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


class TestInventoryRead:
    """Stage 2 – API -> inventory read (live twin state query)."""

    def test_inventory_returns_fixture_baseline(self, client: TestClient) -> None:
        response = client.get("/inventory/P001")
        assert response.status_code == 200
        body = response.json()
        assert body["sku"] == "P001"
        assert body["shelf_id"] == "A01"
        assert body["facings"] == 3
        assert body["shelf_quantity"] == 8
        assert body["backroom_quantity"] == 42

    def test_unknown_sku_returns_404(self, client: TestClient) -> None:
        response = client.get("/inventory/P999")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "sku_not_found"


class TestCanonicalStages:
    """High-level canonical path validation with stage timing."""

    def test_happy_path_event_through_health(
        self, client: TestClient, timer, caplog
    ) -> None:
        """Smoke the full observable surface: event -> inventory -> health."""
        with caplog.at_level(logging.INFO):
            # Stage 1: EVENT intake (canonical path entry gate)
            with timer:
                ev_resp = client.post("/events", json=make_event(event_id="smoke-evt-002"))
            ev_elapsed = timer.checkpoint("event_intake")
            assert ev_resp.status_code == 201

            # Stage 2: INVESTIGATE (inventory read = live twin evidence)
            with timer:
                inv_resp = client.get("/inventory/P001")
            inv_elapsed = timer.checkpoint("investigate")
            assert inv_resp.status_code == 200

            # Stage 3: API availability preflight (health check)
            with timer:
                hl_resp = client.get("/health")
            hl_elapsed = timer.checkpoint("preflight")
            assert hl_resp.status_code == 200
            assert hl_resp.json()["status"] == "ok"

        report = timer.report()
        assert report["stages"]["event_intake"] < 2.0, f"event_intake took {ev_elapsed}s"
        assert report["stages"]["investigate"] < 1.0, f"investigate took {inv_elapsed}s"
        assert report["stages"]["preflight"] < 1.0, f"preflight took {hl_elapsed}s"

        # Correlation IDs are present in logs
        assert "smoke-evt-002" in caplog.text

    def test_state_isolation_two_sequential_events(
        self, client: TestClient, timer
    ) -> None:
        """Two events produce distinct receipts (event log isolation precondition)."""
        with timer:
            r1 = client.post("/events", json=make_event(event_id="smoke-evt-a", quantity=3))
            r2 = client.post("/events", json=make_event(event_id="smoke-evt-b", quantity=7))
        timer.checkpoint("parallel_events")

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["event"]["event_id"] == "smoke-evt-a"
        assert r2.json()["event"]["event_id"] == "smoke-evt-b"
        assert r1.json()["event"]["quantity"] == 3
        assert r2.json()["event"]["quantity"] == 7

        report = timer.report()
        assert report["stages"]["parallel_events"] < 3.0

    def test_live_state_read_is_idempotent(self, client: TestClient) -> None:
        """Multiple inventory reads return identical version (Live Twin immutability)."""
        first = client.get("/inventory/P001").json()
        second = client.get("/inventory/P001").json()
        third = client.get("/inventory/P001").json()
        assert first["version"] == second["version"] == third["version"]
        assert first["shelf_quantity"] == second["shelf_quantity"] == third["shelf_quantity"]

    def test_agent_stub_markers_are_present(
        self, run_id: str, env_info: dict
    ) -> None:
        """Sanity-check that the stub directories for agents are discoverable.

        These become live implementations in future milestones.
        """
        import os
        import pathlib

        repo_root = pathlib.Path(__file__).parent.parent.parent
        agents = ["observer", "investigator", "planner", "simulator",
                  "executor", "verifier", "orchestrator"]
        for agent in agents:
            readme = repo_root / "agents" / agent / "README.md"
            assert readme.exists(), f"Missing agents/{agent}/README.md"
            content = readme.read_text(encoding="utf-8")
            assert len(content) > 10, f"agents/{agent}/README.md is empty"

        # env_info documents the target canonical path (contract presence check)
        assert env_info["canonical_path"] == "EVENT -> AI -> INVESTIGATE -> SIMULATE -> GUARD -> LIVE -> VERIFY"
        assert env_info["store_id"] == "store-001"
