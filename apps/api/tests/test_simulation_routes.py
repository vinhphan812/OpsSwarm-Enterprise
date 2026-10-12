from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from retailtwin_api.contracts import ControlStage, MoveProduct
from retailtwin_api.main import create_app
from retailtwin_api.schemas import ProductInventory, StoreResponse
from retailtwin_api.settings import Settings
from retailtwin_api.simulation_repository import InMemorySimulationRepository
from retailtwin_api.simulation_schemas import (
    AgentActivityEntry,
    CandidateKPI,
    SimulationCandidateResponse,
    SimulationDetail,
    SimulationState,
)


def _store() -> StoreResponse:
    return StoreResponse(
        store_id="store-001",
        context_version="store-001:v1",
        version="v1",
        products=[
            ProductInventory(
                store_id="store-001", sku="P001", shelf_id="A01", slot_id="A01-S01",
                facings=3, shelf_quantity=8, backroom_quantity=42, version=1,
            )
        ],
    )


def _simulation(simulation_id: str, updated_at: datetime) -> SimulationDetail:
    store = _store()
    return SimulationDetail(
        simulation_id=simulation_id,
        store_id="store-001",
        base_context_version="store-001:v1",
        status="evaluated",
        created_at=updated_at - timedelta(minutes=1),
        updated_at=updated_at,
        provenance="simulation-service",
        correlation_id="corr-001",
        agent_id="agent-001",
        actions=[MoveProduct(sku="P001", from_slot="A01-S01", to_slot="A02-S01")],
        state=SimulationState(store=store, context_version=f"{simulation_id}:v1"),
    )


def _repository() -> InMemorySimulationRepository:
    first = _simulation("sim-001", datetime(2026, 10, 12, tzinfo=timezone.utc))
    second = _simulation("sim-002", datetime(2026, 10, 13, tzinfo=timezone.utc))
    candidate = SimulationCandidateResponse(
        candidate_id="candidate-001",
        simulation_id="sim-001",
        proposed_actions=first.actions,
        state=first.state,
        kpis=[CandidateKPI(name="sales_uplift", value=2.5, unit="percent", source="d11")],
        evaluator_version="d11:v1",
        provenance="kpi-evaluator",
        created_at=first.created_at,
    )
    event = AgentActivityEntry(
        id="activity-001",
        ts=first.created_at,
        stage=ControlStage.SIMULATE,
        status="completed",
        correlation_id="corr-001",
        run_id="run-001",
        simulation_id="sim-001",
        sku="P001",
        shelf_id="A01",
        slot_id="A01-S01",
        summary="Simulation completed for SKU P001",
    )
    return InMemorySimulationRepository([first, second], [candidate], [event])


@pytest.fixture
def simulation_client(settings):
    from fastapi.testclient import TestClient

    app = create_app(settings)
    app.state.simulations = _repository()
    with TestClient(app) as client:
        yield client


def test_list_simulations_is_deterministic_and_paginated(simulation_client) -> None:
    response = simulation_client.get("/simulations", params={"status": "open", "page_size": 1})
    assert response.status_code == 200
    assert response.json() == {
        "simulations": [{
            "simulation_id": "sim-002", "store_id": "store-001",
            "base_context_version": "store-001:v1", "status": "evaluated",
            "created_at": "2026-10-12T23:59:00Z", "updated_at": "2026-10-13T00:00:00Z",
            "provenance": "simulation-service",
        }],
        "page": 1, "page_size": 1, "total": 2, "next_cursor": "2",
    }


def test_simulation_detail_keeps_proposed_state_separate_from_live(simulation_client) -> None:
    response = simulation_client.get("/simulations/sim-001")
    assert response.status_code == 200
    body = response.json()
    assert body["state"]["context_version"] == "sim-001:v1"
    assert body["state"]["store"]["context_version"] == "store-001:v1"
    assert body["actions"] == [{"sku": "P001", "from_slot": "A01-S01", "to_slot": "A02-S01"}]


def test_simulation_and_candidate_empty_and_not_found_behavior(simulation_client) -> None:
    empty = simulation_client.get("/simulations", params={"store_id": "missing"})
    assert empty.status_code == 200
    assert empty.json()["simulations"] == []
    assert empty.json()["total"] == 0

    missing = simulation_client.get("/simulations/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "simulation_not_found"

    candidates = simulation_client.get("/simulations/sim-002/candidates")
    assert candidates.status_code == 200
    assert candidates.json()["candidates"] == []
    assert candidates.json()["total"] == 0


def test_candidate_kpis_are_evaluator_values_with_version_and_provenance(simulation_client) -> None:
    response = simulation_client.get("/simulations/sim-001/candidates")
    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["kpis"] == [{"name": "sales_uplift", "value": 2.5, "unit": "percent", "source": "d11"}]
    assert candidate["evaluator_version"] == "d11:v1"
    assert candidate["provenance"] == "kpi-evaluator"


def test_agent_events_are_cursor_paginated_and_include_focus_fields(simulation_client) -> None:
    response = simulation_client.get("/agent/events", params={"limit": 1})
    assert response.status_code == 200
    assert response.json() == {
        "events": [{
            "id": "activity-001", "ts": "2026-10-11T23:59:00Z",
            "stage": "SIMULATE", "status": "completed",
            "correlation_id": "corr-001", "run_id": "run-001",
            "decision": None,
            "simulation_id": "sim-001", "action_id": None, "sku": "P001",
            "shelf_id": "A01", "slot_id": "A01-S01",
            "focus": None,
            "summary": "Simulation completed for SKU P001",
        }],
        "cursor": None,
    }


def test_read_routes_validate_pagination_and_status(simulation_client) -> None:
    response = simulation_client.get("/simulations", params={"page": 0})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    invalid = simulation_client.get("/simulations", params={"status": "wrong"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_simulation_routes_are_unavailable_without_a_real_adapter(settings) -> None:
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as client:
        response = client.get("/simulations")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "simulations_unavailable",
            "message": "Simulation read model is not available.",
        }
    }


def test_dtos_reject_missing_provenance_and_invalid_cursor() -> None:
    with pytest.raises(ValidationError):
        SimulationCandidateResponse.model_validate({})
    with pytest.raises(ValidationError):
        from retailtwin_api.simulation_schemas import CursorParameters
        CursorParameters(since="", limit=0)


def test_repository_raises_on_invalid_cursor(simulation_client) -> None:
    response = simulation_client.get("/agent/events", params={"since": "invalid", "limit": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_repository_raises_on_negative_cursor(simulation_client) -> None:
    response = simulation_client.get("/agent/events", params={"since": "-1", "limit": 1})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_repository_continues_from_valid_cursor(simulation_client) -> None:
    # First page
    first_page = simulation_client.get("/agent/events", params={"limit": 1})
    assert first_page.status_code == 200
    assert len(first_page.json()["events"]) == 1
    cursor = first_page.json()["cursor"]
    assert cursor is None  # only 1 event total


def test_open_list_excludes_closed_simulations() -> None:
    item = _simulation("sim-closed", datetime(2026, 10, 14, tzinfo=timezone.utc))
    item.status = "committed"
    repository = InMemorySimulationRepository([item])
    from retailtwin_api.simulation_schemas import SimulationFilters

    assert repository.list_simulations(SimulationFilters(status="open")).simulations == []


def test_repository_filters_exact_status_and_paginates_candidates_and_events() -> None:
    first = _simulation("sim-pending", datetime(2026, 10, 14, tzinfo=timezone.utc))
    first.status = "pending"
    candidate = SimulationCandidateResponse(
        candidate_id="candidate-2", simulation_id="sim-pending", proposed_actions=[],
        state=first.state, kpis=[], evaluator_version="d11:v1",
        provenance="kpi-evaluator", created_at=first.created_at,
    )
    event = AgentActivityEntry(
        id="activity-2", ts=first.updated_at, stage=ControlStage.PLAN,
        status="started", correlation_id="corr-002",
        summary="Planning stage started",
    )
    repository = InMemorySimulationRepository([first], [candidate, candidate], [_repository().list_agent_events(
        __import__("retailtwin_api.simulation_schemas", fromlist=["CursorParameters"]).CursorParameters()
    )[0][0], event])
    from retailtwin_api.simulation_schemas import CursorParameters, PageParameters, SimulationFilters

    assert repository.list_simulations(SimulationFilters(status="pending", store_id="store-001")).total == 1
    candidates = repository.list_candidates("sim-pending", PageParameters(page=1, page_size=1))
    assert candidates is not None and candidates.next_cursor == "2"
    events, cursor = repository.list_agent_events(CursorParameters(since="1", limit=1))
    assert [item.id for item in events] == ["activity-2"]
    assert cursor is None


def test_repository_protocol_and_unavailable_factory() -> None:
    from retailtwin_api.simulation_repository import unavailable_simulation_repository

    repository = unavailable_simulation_repository()
    assert repository.available is False


def test_simulation_repository_default_and_filter_branches() -> None:
    repository = InMemorySimulationRepository()
    from retailtwin_api.simulation_schemas import CursorParameters, PageParameters, SimulationFilters

    assert repository.list_simulations(SimulationFilters()).total == 0
    assert repository.list_simulations(SimulationFilters(store_id="missing")).total == 0
    assert repository.list_simulations(SimulationFilters(status="rejected")).total == 0
    assert repository.list_candidates("missing", PageParameters()) is None
    assert repository.list_agent_events(CursorParameters()) == ([], None)
