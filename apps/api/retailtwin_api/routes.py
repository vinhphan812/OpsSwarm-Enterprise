"""Day-0 routes. Live Twin mutation stays behind the guard and the executor."""

import json
import logging

from fastapi import APIRouter, Depends, Request, Response

from retailtwin_api.errors import ApiError
from retailtwin_api.events import EventConflict, EventLog
from retailtwin_api.schemas import EventReceipt, HealthResponse, ProductInventory, StoreEvent, StoreResponse
from retailtwin_api.store import StoreRepository

logger = logging.getLogger(__name__)
router = APIRouter()


def get_store(request: Request) -> StoreRepository:
    return request.app.state.store


def get_events(request: Request) -> EventLog:
    return request.app.state.events


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
