"""Tests for GET /simulations and GET /simulations/{simulation_id}."""

import pytest
from starlette.testclient import TestClient


class TestListSimulations:
    def test_returns_list(self, client: TestClient) -> None:
        response = client.get("/simulations")
        assert response.status_code == 200
        data = response.json()
        assert "simulations" in data
        assert isinstance(data["simulations"], list)
        assert len(data["simulations"]) == 1

    def test_returns_seed_simulation(self, client: TestClient) -> None:
        response = client.get("/simulations")
        data = response.json()["simulations"][0]
        assert data["simulation_id"] == "sim-seed-001"
        assert data["store_id"] == "store-001"
        assert data["status"] == "pending"
        assert "base_context_version" in data

    def test_filter_by_open_returns_seed(self, client: TestClient) -> None:
        response = client.get("/simulations?status=open")
        assert response.status_code == 200
        data = response.json()["simulations"]
        ids = [s["simulation_id"] for s in data]
        assert "sim-seed-001" in ids

    def test_filter_by_unknown_status_returns_empty(self, client: TestClient) -> None:
        response = client.get("/simulations?status=rejected")
        assert response.status_code == 200
        assert response.json()["simulations"] == []


class TestGetSimulation:
    def test_returns_detail(self, client: TestClient) -> None:
        response = client.get("/simulations/sim-seed-001")
        assert response.status_code == 200
        data = response.json()
        assert data["simulation_id"] == "sim-seed-001"
        assert data["store_id"] == "store-001"
        assert data["status"] == "pending"
        assert "base_context_version" in data
        assert "state" in data
        assert "actions" in data

    def test_actions_have_correct_count(self, client: TestClient) -> None:
        response = client.get("/simulations/sim-seed-001")
        actions = response.json()["actions"]
        assert len(actions) == 2

    def test_move_action_has_required_fields(self, client: TestClient) -> None:
        response = client.get("/simulations/sim-seed-001")
        actions = response.json()["actions"]
        move = next(
            a for a in actions
            if a.get("from_slot") is not None and a.get("to_slot") is not None
        )
        assert move["sku"] == "P001"
        assert move["from_slot"] == "A01-S01"
        assert move["to_slot"] == "A01-S02"

    def test_facings_action_has_required_fields(self, client: TestClient) -> None:
        response = client.get("/simulations/sim-seed-001")
        actions = response.json()["actions"]
        facings = next(a for a in actions if a.get("facings") is not None)
        assert facings["sku"] == "P001"
        assert facings["facings"] == 5

    def test_proposed_state_differs_from_base(self, client: TestClient) -> None:
        response = client.get("/simulations/sim-seed-001")
        data = response.json()
        state = data["state"]
        store = state["store"]
        assert store["store_id"] == "store-001"
        assert state["context_version"].startswith("store-001:v1+sim:")
        products = {p["sku"]: p for p in store["products"]}
        assert products["P001"]["slot_id"] == "A01-S02"
        assert products["P001"]["facings"] == 5
        assert products["P001"]["shelf_quantity"] == 8

    def test_not_found_returns_404(self, client: TestClient) -> None:
        response = client.get("/simulations/nonexistent-id")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "simulation_not_found"


class TestSimulationStaysReadOnly:
    def test_get_does_not_mutate_simulation(self, client: TestClient) -> None:
        first = client.get("/simulations/sim-seed-001").json()
        second = client.get("/simulations/sim-seed-001").json()
        assert first["status"] == second["status"] == "pending"
        assert (first["state"]["store"]["products"][0]["slot_id"]
                == second["state"]["store"]["products"][0]["slot_id"]
                == "A01-S02")
