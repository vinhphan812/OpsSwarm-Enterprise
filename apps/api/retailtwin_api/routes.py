"""Day-0 routes. Live Twin mutation stays behind the guard and the executor."""

import json
import logging
from typing import Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response

from retailtwin_api.errors import ApiError
from retailtwin_api.events import EventConflict, EventLog
from retailtwin_api.schemas import EventReceipt, HealthResponse, ProductInventory, StoreEvent, StoreResponse
from retailtwin_api.simulation_repository import SimulationReadRepository
from retailtwin_api.simulation_schemas import (
    AgentEventListResponse, CandidateListResponse, CursorParameters, PageParameters,
    SimulationDetail, SimulationFilters, SimulationListResponse, SimulationStatus,
)
from retailtwin_api.store import StoreRepository

logger = logging.getLogger(__name__)
router = APIRouter()


def get_store(request: Request) -> StoreRepository:
    return request.app.state.store  # type: ignore[no-any-return]


def get_events(request: Request) -> EventLog:
    return request.app.state.events  # type: ignore[no-any-return]


def get_simulations(request: Request) -> SimulationReadRepository:
    return request.app.state.simulations  # type: ignore[no-any-return]


def require_simulations(repository: SimulationReadRepository) -> None:
    if not repository.available:
        raise ApiError(503, "simulations_unavailable", "Simulation read model is not available.")


def require_loaded(store: StoreRepository) -> None:
    if not store.loaded:
        raise ApiError(503, "store_unavailable", "Store fixture is not available.")


@router.get("/health", response_model=HealthResponse)
def health(request: Request, store: StoreRepository = Depends(get_store)) -> HealthResponse:
    return HealthResponse(
        status="ok" if store.loaded else "degraded",
        service="retailtwin-api",
        environment=request.app.state.settings.app_env,
        store_id=store.store_id,
        fixture_loaded=store.loaded,
    )


@router.get("/store", response_model=StoreResponse)
def read_store(store: StoreRepository = Depends(get_store)) -> StoreResponse:
    require_loaded(store)
    return store.view()


@router.get("/inventory/{sku}", response_model=ProductInventory)
def read_inventory(sku: str, store: StoreRepository = Depends(get_store)) -> ProductInventory:
    require_loaded(store)
    product = store.inventory(sku)
    if product is None:
        raise ApiError(404, "sku_not_found", f"SKU {sku!r} is not in store {store.store_id}.")
    return product


@router.post("/events", response_model=EventReceipt)
def accept_event(
    event: StoreEvent,
    response: Response,
    store: StoreRepository = Depends(get_store),
    events: EventLog = Depends(get_events),
) -> EventReceipt:
    require_loaded(store)
    stored_event = events.get(event.event_id)
    if stored_event is not None:
        if stored_event == event:
            response.status_code = 200
            _log_event(stored_event, duplicate=True)
            return EventReceipt(duplicate=True, event=stored_event)
        raise ApiError(
            409,
            "event_id_conflict",
            f"Event {event.event_id!r} already exists with a different payload.",
        )
    if event.store_id != store.store_id:
        raise ApiError(404, "store_not_found", f"Store {event.store_id!r} is not served by this API.")
    if store.inventory(event.sku) is None:
        raise ApiError(404, "sku_not_found", f"SKU {event.sku!r} is not in store {store.store_id}.")
    # Record only. Shelf quantity stays on the read model until an authorized executor runs.
    try:
        stored, duplicate = events.accept(event)
    except EventConflict as exc:
        raise ApiError(
            409,
            "event_id_conflict",
            f"Event {exc.event_id!r} already exists with a different payload.",
        ) from exc
    response.status_code = 200 if duplicate else 201
    _log_event(stored, duplicate)
    return EventReceipt(duplicate=duplicate, event=stored)


def _log_event(event: StoreEvent, duplicate: bool) -> None:
    logger.info(
        json.dumps(
            {
                "message": "event.accepted",
                "event_id": event.event_id,
                "correlation_id": event.correlation_id,
                "store_id": event.store_id,
                "duplicate": duplicate,
            }
        )
    )



@router.get("/simulations", response_model=SimulationListResponse)
def list_simulations(
    status: str | None = Query(default=None, pattern="^(pending|evaluated|committed|rejected|open)$"),
    store_id: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    repository: SimulationReadRepository = Depends(get_simulations),
) -> SimulationListResponse:
    require_simulations(repository)
    return repository.list_simulations(
        SimulationFilters(
            status=cast(SimulationStatus | Literal["open"] | None, status),
            store_id=store_id,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/simulations/{simulation_id}", response_model=SimulationDetail)
def read_simulation(simulation_id: str, repository: SimulationReadRepository = Depends(get_simulations)) -> SimulationDetail:
    require_simulations(repository)
    item = repository.get_simulation(simulation_id)
    if item is None:
        raise ApiError(404, "simulation_not_found", f"Simulation {simulation_id!r} was not found.")
    return item


@router.get("/simulations/{simulation_id}/candidates", response_model=CandidateListResponse)
def list_candidates(
    simulation_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    repository: SimulationReadRepository = Depends(get_simulations),
) -> CandidateListResponse:
    require_simulations(repository)
    result = repository.list_candidates(simulation_id, PageParameters(page=page, page_size=page_size))
    if result is None:
        raise ApiError(404, "simulation_not_found", f"Simulation {simulation_id!r} was not found.")
    return result


@router.get("/agent/events", response_model=AgentEventListResponse)
def list_agent_events(
    since: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    repository: SimulationReadRepository = Depends(get_simulations),
) -> AgentEventListResponse:
    require_simulations(repository)
    try:
        events, cursor = repository.list_agent_events(CursorParameters(since=since, limit=limit))
    except ValueError as exc:
        raise ApiError(422, "invalid_cursor", str(exc)) from exc
    return AgentEventListResponse(events=events, cursor=cursor)
