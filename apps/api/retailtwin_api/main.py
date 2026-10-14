"""FastAPI application for the RetailTwin day-0 boundary."""

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from retailtwin_api.agents.executor import build_commit_service
from retailtwin_api.analytics_repository import unavailable_analytics_repositories
from retailtwin_api.decisions import unavailable_decision_source
from retailtwin_api.errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from retailtwin_api.events import EventLog, ReviewAuditLog
from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository, LiveTwinRepository
from retailtwin_api.guard.decision_context_guard import InMemoryGuardAudit
from retailtwin_api.middleware import CorrelationMiddleware
from retailtwin_api.routes import router
from retailtwin_api.settings import Settings, get_settings
from retailtwin_api.simulation import SimulationRepository
from retailtwin_api.store import LiveTwinStore, StoreReader, open_memory_live_store, open_store

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    app = FastAPI(
        title="RetailTwin API",
        version="0.1.0",
        description="Day-0 retail store event API. Structured JSON logs and "
        "correlation IDs are enabled in all environments.",
    )
    app.state.settings = resolved

    # Default is an in-process Live Twin seeded from the fixture. Firestore is
    # used only when LIVE_TWIN_BACKEND=firestore, so tests never open a live project.
    store = _open_store(resolved)
    app.state.store = store
    live_twin: LiveTwinRepository | None = store.twin if isinstance(store, LiveTwinStore) else None
    app.state.live_twin = live_twin
    app.state.guard_audit = InMemoryGuardAudit()
    app.state.commits = (
        build_commit_service(live_twin, app.state.guard_audit, production=resolved.is_production)
        if live_twin is not None
        else None
    )
    # The planner does not persist Decisions yet. A test or a later orchestrator injects a source.
    app.state.decisions = unavailable_decision_source()
    app.state.events = EventLog()
    app.state.review_audit = ReviewAuditLog()
    app.state.live_context_version = store.view().context_version if store.loaded else ""
    app.state.simulations = SimulationRepository(store.view, resolved.store_id)
    if not store.loaded:
        logger.error(
            "fixture.unavailable",
            extra={"store_error": store.error, "fixture_path": str(resolved.store_fixture_path)},
        )
    # Analytics repositories: GCP-backed (BigQuery + Firestore); empty adapters in dev.
    # Swap app.state.anomalies / .revenue / .promotions in integration tests.
    anomalies, revenue, promotions = unavailable_analytics_repositories()
    app.state.anomalies = anomalies
    app.state.revenue = revenue
    app.state.promotions = promotions

    # Correlation + structured logging middleware (must be outermost)
    app.add_middleware(CorrelationMiddleware)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins(resolved.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["accept", "content-type", "x-correlation-id"],
    )
    app.include_router(router)

    logger.info(
        "app.startup",
        extra={
            "app_env": resolved.app_env,
            "is_production": resolved.is_production,
            "store_id": resolved.store_id,
            "fixture_loaded": store.loaded,
            "fixture_path": str(resolved.store_fixture_path),
            "live_twin_backend": resolved.live_twin_backend,
        },
    )
    return app


def _open_store(settings: Settings) -> StoreReader:
    if settings.live_twin_backend == "fixture":
        return open_store(settings.store_fixture_path, settings.store_id)
    if settings.live_twin_backend == "firestore":
        return LiveTwinStore(FirestoreLiveTwinRepository(), settings.store_id)
    return open_memory_live_store(settings.store_fixture_path, settings.store_id)


def _origins(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "retailtwin_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
