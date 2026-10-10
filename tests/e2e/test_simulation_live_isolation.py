"""
test_simulation_live_isolation.py

Tests for simulation/live state separation and isolation.

Covered scenarios:
  G02 / G05 isolation gates (planned):
    - Simulation Twin state is never shared with Live Twin
    - Executor commits only to Live Twin, never directly mutating Simulation
    - Inventory version is unchanged by event intake (Live immutability)
    - DCG can read Simulation output but not commit from it

Current status:
    Both Simulation and Live Twin are represented by the same read-only fixture.
    These tests verify the isolation surface that must hold once the twin
    services are separated into live and simulation branches.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import make_event


class TestLiveStateImmutability:
    """Live Twin inventory cannot be mutated by event intake (G05 pre-requisite)."""

    def test_event_intake_does_not_change_live_inventory(
        self, client: TestClient
    ) -> None:
        """POST /events records the event but does not mutate shelf_quantity."""
        before = client.get("/inventory/P001").json()
        for i in range(3):
            client.post("/events", json=make_event(event_id=f"smoke-iso-{i}"))
        after = client.get("/inventory/P001").json()
        assert after["shelf_quantity"] == before["shelf_quantity"]
        assert after["version"] == before["version"]

    def test_inventory_version_is_stable_under_multiple_events(
        self, client: TestClient
    ) -> None:
        """Version increments only on Executor commit, not on event intake."""
        responses = [client.post("/events", json=make_event()) for _ in range(5)]
        for r in responses:
            assert r.status_code == 201
        inv = client.get("/inventory/P001").json()
        assert inv["version"] == 1  # fixture baseline

    def test_multiple_events_do_not_accumulate_in_live_twin(
        self, client: TestClient
    ) -> None:
        """Events are logged; inventory is unchanged. Simulation processes them."""
        for i in range(4):
            client.post("/events", json=make_event(event_id=f"smoke-iso-evt-{i}"))
        inv = client.get("/inventory/P001").json()
        store = client.get("/store").json()
        assert store["context_version"] == "store-001:v1"
        assert inv["version"] == 1


class TestSimulationServiceContract:
    """Simulation Twin must be a separate mutation path from Live Twin."""

    def test_simulation_service_directory_exists(self) -> None:
        """Simulation service directory is present (stub implementation next)."""
        import pathlib
        repo_root = pathlib.Path(__file__).parent.parent.parent
        sim_readme = repo_root / "services" / "simulation" / "README.md"
        assert sim_readme.exists()
        content = sim_readme.read_text(encoding="utf-8")
        assert "Simulation" in content
        assert "clone" in content.lower() or "snapshot" in content.lower()

    def test_twin_service_directory_exists(self) -> None:
        """Twin service is the canonical Live Twin access layer."""
        import pathlib
        repo_root = pathlib.Path(__file__).parent.parent.parent
        twin_readme = repo_root / "services" / "twin" / "README.md"
        assert twin_readme.exists()
        content = twin_readme.read_text(encoding="utf-8")
        assert "Twin" in content
        assert "Store" in content

    def test_dcg_directory_exists(self) -> None:
        """Decision Context Guard contract is defined."""
        import pathlib
        repo_root = pathlib.Path(__file__).parent.parent.parent
        dcg_dir = repo_root / "guard" / "decision-context-guard"
        assert dcg_dir.exists()
        contract = dcg_dir / "contract.schema.json"
        assert contract.exists()
        import json
        data = json.loads(contract.read_text(encoding="utf-8"))
        assert data["title"] == "RetailTwinDecision"
        assert "context_version" in data["required"]


class TestExecutorIsolation:
    """Executor is the sole live mutation path (stub at day-0)."""

    def test_executor_readme_mentions_authorization(self) -> None:
        """Executor README documents the authorization requirement."""
        import pathlib
        repo_root = pathlib.Path(__file__).parent.parent.parent
        exec_readme = repo_root / "agents" / "executor" / "README.md"
        assert exec_readme.exists()
        content = exec_readme.read_text(encoding="utf-8")
        assert "authorization" in content.lower() or "commit" in content.lower()

    def test_guard_readme_mentions_outcomes(self) -> None:
        """DCG README documents ALLOW / DENY / REFRESH_REQUIRED outcomes."""
        import pathlib
        repo_root = pathlib.Path(__file__).parent.parent.parent
        guard_dir = repo_root / "guard" / "decision-context-guard"
        readme = guard_dir / "README.md"
        assert readme.exists()
        content = readme.read_text(encoding="utf-8")
        for outcome in ("ALLOW", "DENY", "REFRESH_REQUIRED"):
            assert outcome in content, f"Missing outcome {outcome} in DCG README"


class TestStateResetDeterminism:
    """Live state reset must be deterministic (no manual DB patches)."""

    def test_store_fixture_is_deterministic(self, client: TestClient) -> None:
        """The fixture baseline is identical across restarts."""
        store = client.get("/store").json()
        assert store["store_id"] == "store-001"
        assert store["context_version"] == "store-001:v1"
        assert store["products"][0]["sku"] == "P001"
        assert store["products"][0]["shelf_quantity"] == 8
        assert store["products"][0]["version"] == 1

    def test_inventory_fixture_is_deterministic(self, client: TestClient) -> None:
        """Inventory values are stable fixture constants."""
        p001 = client.get("/inventory/P001").json()
        assert p001["shelf_quantity"] == 8
        assert p001["backroom_quantity"] == 42
        assert p001["version"] == 1

    def test_health_is_stable_without_mutation(self, client: TestClient) -> None:
        """Health reflects stable fixture + in-memory event log only."""
        h1 = client.get("/health").json()
        client.post("/events", json=make_event())
        h2 = client.get("/health").json()
        # Fixture loaded status is unchanged by events
        assert h1["fixture_loaded"] == h2["fixture_loaded"]
        assert h1["status"] == h2["status"]
        assert h1["store_id"] == h2["store_id"]
