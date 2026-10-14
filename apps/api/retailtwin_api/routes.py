"""Day-0 routes. Live Twin mutation stays behind the guard and the executor."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response

from retailtwin_api.errors import ApiError
from retailtwin_api.events import EventConflict, EventLog, ReviewAuditLog
from retailtwin_api.schemas import (
    AnomaliesResponse,
    AnomalySeverity,
    AnomalyType,
    EventReceipt,
    HealthResponse,
    ProductInventory,
    PromotionStatus,
    PromotionsResponse,
    ReadyResponse,
    RevenueResponse,
    StoreEvent,
    StoreResponse,
)
from retailtwin_api.analytics_repository import AnomalyRepository, RevenueRepository, PromotionRepository
from retailtwin_api.simulation_repository import SimulationReadRepository
from retailtwin_api.simulation_schemas import (
    AgentEventListResponse, CandidateListResponse, CursorParameters, PageParameters,
    DecisionReviewReasonCode, DecisionReviewVerdict,
    SimulationDetail, SimulationFilters, SimulationListResponse, SimulationStatus,
    SimulationReviewRequest, SimulationReviewResponse,
)
from retailtwin_api.store import StoreRepository

logger = logging.getLogger(__name__)
router = APIRouter()


def get_store(request: Request) -> StoreRepository:
    return request.app.state.store


def get_events(request: Request) -> EventLog:
    return request.app.state.events


def get_simulations(request: Request) -> SimulationReadRepository:
    return request.app.state.simulations


def get_anomalies(request: Request) -> AnomalyRepository:
    return request.app.state.anomalies


def get_revenue_repo(request: Request) -> RevenueRepository:
    return request.app.state.revenue


def get_promotions(request: Request) -> PromotionRepository:
    return request.app.state.promotions


def require_simulations(repository: SimulationReadRepository) -> None:
    if not repository.available:
        raise ApiError(503, "simulations_unavailable", "Simulation read model is not available.")


def require_loaded(store: StoreRepository) -> None:
    if not store.loaded:
        raise ApiError(503, "store_unavailable", "Store fixture is not available.")


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "no-correlation-id")


@router.get("/health", response_model=HealthResponse, include_in_schema=True)
def health(request: Request, store: StoreRepository = Depends(get_store)) -> HealthResponse:
    """Liveness probe: is the process alive? Always returns 200 if the container is running."""
    return HealthResponse(
        status="ok" if store.loaded else "degraded",
        service="retailtwin-api",
        environment=request.app.state.settings.app_env,
        app_env=request.app.state.settings.app_env,
        store_id=store.store_id,
        fixture_loaded=store.loaded,
    )


@router.get("/ready", response_model=ReadyResponse, include_in_schema=True)
def ready(request: Request, store: StoreRepository = Depends(get_store)) -> ReadyResponse:
    """Readiness probe: can the service handle traffic?

    Returns 503 when the store fixture is unavailable, causing Cloud Run
    load-balancer to drain traffic away from this instance until the
    fixture is reloaded.
    """
    if not store.loaded:
        raise ApiError(503, "store_unavailable", "Store fixture is not available.")
    return ReadyResponse(
        ready=True,
        service="retailtwin-api",
        store_id=store.store_id,
        correlation_id=_correlation_id(request),
    )


@router.get("/store", response_model=StoreResponse, include_in_schema=True)
def read_store(request: Request, store: StoreRepository = Depends(get_store)) -> StoreResponse:
    require_loaded(store)
    return store.view()


@router.get("/inventory/{sku}", response_model=ProductInventory, include_in_schema=True)
def read_inventory(request: Request, sku: str, store: StoreRepository = Depends(get_store)) -> ProductInventory:
    require_loaded(store)
    product = store.inventory(sku)
    if product is None:
        logger.warning(
            "sku.not_found",
            extra={"correlation_id": _correlation_id(request), "sku": sku, "store_id": store.store_id},
        )
        raise ApiError(404, "sku_not_found", f"SKU {sku!r} is not in store {store.store_id}.")
    return product


@router.post("/events", response_model=EventReceipt, include_in_schema=True)
def accept_event(
    request: Request,
    event: StoreEvent,
    response: Response,
    store: StoreRepository = Depends(get_store),
    events: EventLog = Depends(get_events),
) -> EventReceipt:
    require_loaded(store)
    cid = _correlation_id(request)
    stored_event = events.get(event.event_id)
    if stored_event is not None:
        if stored_event == event:
            response.status_code = 200
            _log_event(stored_event, duplicate=True, correlation_id=cid)
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
    _log_event(stored, duplicate=duplicate, correlation_id=cid)
    return EventReceipt(duplicate=duplicate, event=stored)


def _log_event(event: StoreEvent, duplicate: bool, correlation_id: str) -> None:
    msg = f"event.accepted event_id={event.event_id} duplicate={duplicate} store_id={event.store_id} correlation_id={correlation_id}"
    logger.info(
        msg,
        extra={
            "correlation_id": correlation_id,
            "event_id": event.event_id,
            "correlation_id_header": event.correlation_id,
            "store_id": event.store_id,
            "duplicate": duplicate,
        },
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


# ─── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/anomalies", response_model=AnomaliesResponse, include_in_schema=True)
def list_anomalies(
    request: Request,
    severity: AnomalySeverity | None = Query(default=None),
    anomaly_type: AnomalyType | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    store_id: str | None = Query(default=None, min_length=1),
    repo: AnomalyRepository = Depends(get_anomalies),
) -> AnomaliesResponse:
    """Return detected anomalies for a store, newest first."""
    target_store = store_id or request.app.state.settings.store_id
    return repo.list_anomalies(
        store_id=target_store,
        severity=severity,
        anomaly_type=anomaly_type,
        since=since,
        limit=limit,
    )


@router.get("/revenue", response_model=RevenueResponse, include_in_schema=True)
def get_revenue(
    request: Request,
    period: Literal["hourly", "daily", "weekly", "monthly"] = Query(default="daily"),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    store_id: str | None = Query(default=None, min_length=1),
    repo: RevenueRepository = Depends(get_revenue_repo),
) -> RevenueResponse:
    """Return revenue aggregates for a store over the requested period."""
    target_store = store_id or request.app.state.settings.store_id
    now = datetime.now(timezone.utc)
    period_start = start or (now - timedelta(days=1))
    period_end = end or now
    if period_start > period_end:
        raise ApiError(422, "invalid_range", "start must be before end.")
    return repo.get_revenue(
        store_id=target_store,
        period=period,
        start=period_start,
        end=period_end,
    )


@router.get("/promotions", response_model=PromotionsResponse, include_in_schema=True)
def list_promotions(
    request: Request,
    status: PromotionStatus | None = Query(default=None),
    sku: str | None = Query(default=None, min_length=1),
    category: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    store_id: str | None = Query(default=None, min_length=1),
    repo: PromotionRepository = Depends(get_promotions),
) -> PromotionsResponse:
    """Return promotions for a store, newest first."""
    target_store = store_id or request.app.state.settings.store_id
    return repo.list_promotions(
        store_id=target_store,
        status=status,
        sku=sku,
        category=category,
        limit=limit,
    )


# ─── Simulation review ──────────────────────────────────────────────────────────

def get_review_audit(request: Request) -> ReviewAuditLog:
    return request.app.state.review_audit


def get_live_version(request: Request) -> str:
    return request.app.state.live_context_version


def _run_review(
    simulation_id: str,
    body: SimulationReviewRequest,
    decision: Literal["approved", "rejected"],
    simulations: SimulationReadRepository,
    store: StoreRepository,
    audit: ReviewAuditLog,
    live_version: str,
) -> SimulationReviewResponse:
    """Shared logic for /approve and /reject: version check → simulation check → audit."""
    # 1. Version validation: base_context_version must match live store version
    if body.base_context_version != live_version:
        logger.warning(
            "simulation_review.version_mismatch",
            extra={
                "simulation_id": simulation_id,
                "decision": decision,
                "base_context_version": body.base_context_version,
                "live_context_version": live_version,
            },
        )
        return SimulationReviewResponse(
            simulation_id=simulation_id,
            decision=decision,
            status="pending",
            verdict=DecisionReviewVerdict.REFRESH_REQUIRED,
            reason_code=DecisionReviewReasonCode.VERSION_MISMATCH,
            live_context_version=live_version,
        )

    # 2. Simulation exists and is open (pending | evaluated)
    item = simulations.get_simulation(simulation_id)
    if item is None:
        raise ApiError(
            404,
            "simulation_not_found",
            f"Simulation {simulation_id!r} was not found.",
        )
    if item.status not in ("pending", "evaluated"):
        logger.warning(
            "simulation_review.not_open",
            extra={
                "simulation_id": simulation_id,
                "decision": decision,
                "current_status": item.status,
            },
        )
        return SimulationReviewResponse(
            simulation_id=simulation_id,
            decision=decision,
            status=item.status,
            verdict=DecisionReviewVerdict.DENY,
            reason_code=DecisionReviewReasonCode.SIMULATION_NOT_OPEN,
            live_context_version=live_version,
        )

    # 3. Record audit
    audit.record(
        simulation_id=simulation_id,
        decision=decision,
        base_context_version=body.base_context_version,
        proposal_context_version=body.proposal_context_version,
        live_context_version=live_version,
        verdict=DecisionReviewVerdict.ALLOW,
        reason_code=DecisionReviewReasonCode.APPROVED,
    )
    logger.info(
        f"simulation_review.{decision}",
        extra={
            "simulation_id": simulation_id,
            "decision": decision,
            "base_context_version": body.base_context_version,
            "live_context_version": live_version,
        },
    )

    new_status: SimulationStatus = "committed" if decision == "approved" else "rejected"
    return SimulationReviewResponse(
        simulation_id=simulation_id,
        decision=decision,
        status=new_status,
        verdict=DecisionReviewVerdict.ALLOW,
        reason_code=DecisionReviewReasonCode.APPROVED,
        live_context_version=live_version,
    )


@router.post(
    "/simulations/{simulation_id}/approve",
    response_model=SimulationReviewResponse,
    status_code=200,
)
def approve_simulation(
    simulation_id: str,
    body: SimulationReviewRequest,
    repository: SimulationReadRepository = Depends(get_simulations),
    store: StoreRepository = Depends(get_store),
    audit: ReviewAuditLog = Depends(get_review_audit),
    live_version: str = Depends(get_live_version),
) -> SimulationReviewResponse:
    """Approve a simulation: validate versions, check DCG guard, record audit, commit."""
    require_simulations(repository)
    return _run_review(
        simulation_id=simulation_id,
        body=body,
        decision="approved",
        simulations=repository,
        store=store,
        audit=audit,
        live_version=live_version,
    )


@router.post(
    "/simulations/{simulation_id}/reject",
    response_model=SimulationReviewResponse,
    status_code=200,
)
def reject_simulation(
    simulation_id: str,
    body: SimulationReviewRequest,
    repository: SimulationReadRepository = Depends(get_simulations),
    store: StoreRepository = Depends(get_store),
    audit: ReviewAuditLog = Depends(get_review_audit),
    live_version: str = Depends(get_live_version),
) -> SimulationReviewResponse:
    """Reject a simulation: validate versions, check DCG guard, record audit."""
    require_simulations(repository)
    return _run_review(
        simulation_id=simulation_id,
        body=body,
        decision="rejected",
        simulations=repository,
        store=store,
        audit=audit,
        live_version=live_version,
    )
