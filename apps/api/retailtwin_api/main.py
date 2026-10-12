"""FastAPI application for the RetailTwin day-0 boundary."""

import json
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from retailtwin_api.errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from retailtwin_api.events import EventLog
from retailtwin_api.routes import router
from retailtwin_api.settings import Settings, get_settings
from retailtwin_api.simulation_repository import unavailable_simulation_repository
from retailtwin_api.store import open_store

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    level = getattr(logging, resolved.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level)

    app = FastAPI(title="RetailTwin API", version="0.1.0")
    app.state.settings = resolved
    store = open_store(resolved.store_fixture_path, resolved.store_id)
    app.state.store = store
    app.state.events = EventLog()
    # Production has no implicit demo fixture. An integration injects a real adapter.
    app.state.simulations = unavailable_simulation_repository()
    if not store.loaded:
        logger.error(json.dumps({"message": "fixture.unavailable", "reason": store.error}))

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins(resolved.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["accept", "content-type"],
    )
    app.include_router(router)
    return app


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
