"""POST /simulations/{id}/approve through DCG, a signed token and the guarded Executor (#18)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.contracts import Decision, EvidenceBundle, ExpectedImpact, ReplenishShelf
from retailtwin_api.decisions import InMemoryDecisionSource, unavailable_decision_source
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventoryDocument
from retailtwin_api.guard.decision_context_guard.authorization import SIGNING_KEY_ENV
from retailtwin_api.main import create_app
from retailtwin_api.schemas import ProductInventory, StoreResponse
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.simulation_repository import InMemorySimulationRepository
from retailtwin_api.simulation_schemas import SimulationDetail, SimulationState
from retailtwin_api.store import LiveTwinStore, StoreRepository, open_memory_live_store

SIM = "sim-commit-001"
REVIEW = {"base_context_version": "store-001:v1", "proposal_context_version": f"{SIM}:v1"}


def _simulation(status: str = "evaluated") -> SimulationDetail:
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    product = ProductInventory(
        store_id="store-001", sku="P001", shelf_id="A01", slot_id="A01-S01",
        facings=3, shelf_quantity=14, backroom_quantity=36, version=1,
    )
    return SimulationDetail(
        simulation_id=SIM,
        store_id="store-001",
        base_context_version="store-001:v1",
        status=status,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
        provenance="simulation-service",
        actions=[ReplenishShelf(sku="P001", quantity=6)],
        state=SimulationState(
            store=StoreResponse(store_id="store-001", context_version="store-001:v1", version="v1", products=[product]),
            context_version=f"{SIM}:v1",
        ),
    )


def _decision(*, version: str = "1", quantity: int = 6, sufficient: bool = True, **extra: Any) -> Decision:
    now = datetime.now(timezone.utc)
    fields: dict[str, Any] = {
        "decision_id": "dec-commit-001",
        "agent_id": "planner",
        "context_version": "store-001:v1",
        "context_timestamp": now,
        "evidence": [
            EvidenceBundle(
                bundle_id="b1", provenance="tool-registry", source="investigator",
                entity_versions={"P001": version}, collected_at=now, freshness=now,
                store_id="store-001", correlation_id="corr-commit-001", is_sufficient=sufficient,
            )
        ],
        "proposed_actions": [ReplenishShelf(sku="P001", quantity=quantity)],
        "simulation_id": SIM,
        "expected_impact": ExpectedImpact(kpi_score=0.2, description="restock"),
    }
    fields.update(extra)
    return Decision(**fields)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    app.state.simulations = InMemorySimulationRepository([_simulation()])
    app.state.decisions = InMemoryDecisionSource()
    with TestClient(app) as test_client:
        yield test_client


def _put(client: TestClient, decision: Decision) -> None:
    client.app.state.decisions.put(SIM, decision)  # type: ignore[attr-defined]


def _p001(client: TestClient) -> dict[str, Any]:
    response = client.get("/inventory/P001")
    assert response.status_code == 200
    return response.json()


def _approve(client: TestClient) -> dict[str, Any]:
    response = client.post(f"/simulations/{SIM}/approve", json=REVIEW)
    assert response.status_code == 200, response.text
    return response.json()


def test_allowed_decision_changes_the_live_twin(client: TestClient) -> None:
    _put(client, _decision())
    before = _p001(client)

    body = _approve(client)

    assert (body["verdict"], body["reason_code"], body["status"]) == ("ALLOW", "APPROVED", "committed")
    assert body["live_context_version"] == "store-001:v2"
    assert [check["gate"] for check in body["guard"]["policy_result"]["checks"]] == [
        "integrity", "evidence", "context", "freshness", "feasibility", "policy",
    ]
    after = _p001(client)
    assert (after["shelf_quantity"], after["backroom_quantity"], after["version"]) == (
        before["shelf_quantity"] + 6, before["backroom_quantity"] - 6, before["version"] + 1,
    )
    assert client.get("/store").json()["context_version"] == "store-001:v2"
    [record] = client.app.state.review_audit.get(SIM)  # type: ignore[attr-defined]
    assert (record.verdict, record.reason_code, record.live_context_version) == ("ALLOW", "APPROVED", "store-001:v2")
    stages = [(e.stage, e.verdict.value) for e in client.app.state.guard_audit.events("dec-commit-001")]  # type: ignore[attr-defined]
    assert stages == [("authorize", "ALLOW"), ("commit", "ALLOW")]


def test_second_approval_of_a_committed_simulation_is_refused(client: TestClient) -> None:
    _put(client, _decision())
    _approve(client)
    body = client.post(
        f"/simulations/{SIM}/approve",
        json={"base_context_version": "store-001:v2", "proposal_context_version": f"{SIM}:v1"},
    ).json()
    assert (body["verdict"], body["reason_code"]) == ("DENY", "SIMULATION_NOT_OPEN")
    assert _p001(client)["version"] == 2


def test_stale_decision_cannot_change_the_live_twin(client: TestClient) -> None:
    """G04 through the route: D1 read P001 at N, Live is at N+1."""
    twin: InMemoryTwinRepository = client.app.state.live_twin  # type: ignore[attr-defined]
    current = twin.get_inventory("store-001", "P001")
    assert current is not None
    twin.upsert_inventory(current.model_copy(update={"version": 2}), expected_version=1)
    _put(client, _decision(version="1"))
    before = _p001(client)

    body = _approve(client)

    assert (body["verdict"], body["reason_code"], body["detail_code"]) == ("REFRESH_REQUIRED", "VERSION_STALE", "VERSION_STALE")
    assert body["status"] == "evaluated"
    assert body["live_context_version"] == "store-001:v1"
    assert _p001(client) == before
    sim = client.app.state.simulations.get_simulation(SIM)  # type: ignore[attr-defined]
    assert sim.status == "evaluated"
    [record] = client.app.state.review_audit.get(SIM)  # type: ignore[attr-defined]
    assert record.reason_code == "VERSION_STALE"


def test_denied_decision_changes_nothing(client: TestClient) -> None:
    _put(client, _decision(sufficient=False))
    before = _p001(client)
    body = _approve(client)
    assert (body["verdict"], body["reason_code"], body["detail_code"]) == ("DENY", "DCG_DENY", "INSUFFICIENT_EVIDENCE")
    assert body["guard"]["policy_result"]["failed_gate"] == "evidence"
    assert _p001(client) == before


def test_infeasible_decision_changes_nothing(client: TestClient) -> None:
    _put(client, _decision(quantity=500))
    before = _p001(client)
    body = _approve(client)
    assert (body["verdict"], body["detail_code"]) == ("DENY", "INFEASIBLE_ACTION")
    assert _p001(client) == before


def test_large_change_goes_to_a_person(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETAILTWIN_DCG_MAX_REPLENISH_UNITS", "5")
    app = create_app(settings)
    app.state.simulations = InMemorySimulationRepository([_simulation()])
    app.state.decisions = InMemoryDecisionSource()
    with TestClient(app) as client:
        _put(client, _decision(quantity=6))
        body = _approve(client)
    assert (body["verdict"], body["reason_code"], body["detail_code"]) == ("HUMAN_REVIEW", "DCG_HUMAN_REVIEW", "POLICY_THRESHOLD")


def test_execution_failure_is_reported_and_writes_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    twin: InMemoryTwinRepository = client.app.state.live_twin  # type: ignore[attr-defined]

    def broken(store_id: str, items: Any) -> Any:
        raise RuntimeError("backend detail")

    monkeypatch.setattr(twin, "commit_inventory", broken)
    _put(client, _decision())
    before = _p001(client)
    body = _approve(client)
    assert (body["verdict"], body["reason_code"], body["detail_code"]) == ("DENY", "EXECUTION_FAILED", "EXECUTION_FAILED")
    assert _p001(client) == before


def test_simulation_without_a_decision_is_denied(client: TestClient) -> None:
    before = _p001(client)
    body = _approve(client)
    assert (body["verdict"], body["reason_code"]) == ("DENY", "DECISION_UNAVAILABLE")
    assert _p001(client) == before


def test_decision_for_another_simulation_is_denied(client: TestClient) -> None:
    _put(client, _decision(simulation_id="sim-other"))
    assert _approve(client)["reason_code"] == "DECISION_UNAVAILABLE"


def test_decision_without_a_simulation_id_is_accepted(client: TestClient) -> None:
    _put(client, _decision(simulation_id=None))
    assert _approve(client)["verdict"] == "ALLOW"


def test_unavailable_decision_store_is_503(client: TestClient) -> None:
    client.app.state.decisions = unavailable_decision_source()  # type: ignore[attr-defined]
    response = client.post(f"/simulations/{SIM}/approve", json=REVIEW)
    assert (response.status_code, response.json()["error"]["code"]) == (503, "decisions_unavailable")


def test_fixture_backend_has_no_commit_path(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"live_twin_backend": "fixture"}))
    app.state.simulations = InMemorySimulationRepository([_simulation()])
    with TestClient(app) as client:
        response = client.post(f"/simulations/{SIM}/approve", json=REVIEW)
        assert isinstance(app.state.store, StoreRepository)
        assert app.state.live_twin is None and app.state.commits is None
    assert (response.status_code, response.json()["error"]["code"]) == (503, "commit_unavailable")


def test_production_without_a_signing_key_has_no_commit_path(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SIGNING_KEY_ENV, raising=False)
    app = create_app(settings.model_copy(update={"app_env": "production"}))
    app.state.simulations = InMemorySimulationRepository([_simulation()])
    app.state.decisions = InMemoryDecisionSource()
    with TestClient(app) as client:
        _put(client, _decision())
        response = client.post(f"/simulations/{SIM}/approve", json=REVIEW)
    assert (response.status_code, response.json()["error"]["code"]) == (503, "commit_unavailable")


def test_reject_records_the_status_and_changes_nothing(client: TestClient) -> None:
    _put(client, _decision())
    before = _p001(client)
    body = client.post(f"/simulations/{SIM}/reject", json=REVIEW).json()
    assert (body["status"], body["verdict"]) == ("rejected", "ALLOW")
    assert client.app.state.simulations.get_simulation(SIM).status == "rejected"  # type: ignore[attr-defined]
    assert _p001(client) == before


def test_reject_of_a_closed_simulation_is_refused(client: TestClient) -> None:
    client.app.state.simulations = InMemorySimulationRepository([_simulation("committed")])  # type: ignore[attr-defined]
    body = client.post(f"/simulations/{SIM}/reject", json=REVIEW).json()
    assert (body["verdict"], body["reason_code"]) == ("DENY", "SIMULATION_NOT_OPEN")


def test_reject_of_a_missing_simulation_is_404(client: TestClient) -> None:
    response = client.post("/simulations/nope/reject", json=REVIEW)
    assert response.status_code == 404


# ─── Live Twin store adapter ─────────────────────────────────────────────────


def test_memory_store_serves_the_fixture_like_the_fixture_store() -> None:
    live = open_memory_live_store(DEFAULT_FIXTURE, "store-001")
    fixture = StoreRepository(DEFAULT_FIXTURE, "store-001")
    assert live.loaded and live.error is None
    assert live.view() == fixture.view()
    assert live.inventory("P001") == fixture.inventory("P001")
    assert live.inventory("P404") is None


def test_memory_store_keeps_the_fixture_product_version(tmp_path: Path) -> None:
    fixture = tmp_path / "store.json"
    fixture.write_text(DEFAULT_FIXTURE.read_text(encoding="utf-8").replace('"v1"', '"v4"'), encoding="utf-8")
    live = open_memory_live_store(fixture, "store-001")
    item = live.inventory("P001")
    assert item is not None and item.version == 4
    assert live.view().context_version == "store-001:v4"


def test_memory_store_with_a_missing_fixture_is_not_loaded(tmp_path: Path) -> None:
    live = open_memory_live_store(tmp_path / "missing.json", "store-001")
    assert live.loaded is False
    assert live.error


def test_live_store_without_the_store_document_is_not_loaded() -> None:
    live = LiveTwinStore(InMemoryTwinRepository(), "store-001")
    assert live.loaded is False
    assert live.error == "Store 'store-001' is not in the Live Twin."
    with pytest.raises(RuntimeError):
        live.view()


def test_unreachable_live_twin_is_not_loaded() -> None:
    class Unreachable(InMemoryTwinRepository):
        def get_store(self, store_id: str) -> Any:
            raise ConnectionError("secret host")

    live = LiveTwinStore(Unreachable(), "store-001")
    assert live.loaded is False
    assert live.error == "Live Twin is not available: ConnectionError"


def test_firestore_backend_without_access_starts_unloaded(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from retailtwin_api import main

    class Offline(InMemoryTwinRepository):
        def get_store(self, store_id: str) -> Any:
            raise ConnectionError("no credentials")

    monkeypatch.setattr(main, "FirestoreLiveTwinRepository", Offline)
    app = create_app(settings.model_copy(update={"live_twin_backend": "firestore"}))
    assert isinstance(app.state.store, LiveTwinStore)
    assert app.state.store.loaded is False
    with TestClient(app) as client:
        assert client.get("/store").status_code == 503


def test_inventory_document_round_trips_through_the_adapter() -> None:
    live = open_memory_live_store(DEFAULT_FIXTURE, "store-001")
    doc = live.twin.get_inventory("store-001", "P001")
    assert isinstance(doc, InventoryDocument)
    assert live.inventory("P001") == ProductInventory.model_validate(doc.to_product_inventory())
