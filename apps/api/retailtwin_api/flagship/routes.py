"""HTTP routes for the Flagship controller.

Three commands:

  POST /flagship/reset  → reseed the Live Twin to the canonical fixture
  POST /flagship/start  → run the autonomous chain end-to-end
  GET  /flagship/status → current phase, last result, timeline

Routes are mounted by ``register_routes`` so the same router can be attached
to any FastAPI app the controller is wired into.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from retailtwin_api.flagship.controller import (
    FlagshipController,
    FlagshipRequest,
    FlagshipStateError,
    get_controller,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/flagship", tags=["flagship"])


def _controller(request: Request) -> FlagshipController:
    controller = getattr(request.app.state, "flagship_controller", None)
    if controller is None:
        controller = get_controller()
    return controller


@router.post("/reset")
def reset_route(request: Request) -> dict[str, Any]:
    """Reseed the Live Twin via the controller's reset boundary."""

    controller = _controller(request)
    if not controller.is_configured:
        raise HTTPException(
            status_code=503,
            detail="flagship controller is not configured",
        )
    try:
        return controller.reset()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/start")
async def start_route(
    request: Request,
    body: FlagshipRequest | None = None,
) -> dict[str, Any]:
    """Drive the canonical chain. The body is optional; defaults reproduce the
    flagship scenario with the canonical seed and the deliberate stale block.
    """

    controller = _controller(request)
    if not controller.is_configured:
        raise HTTPException(
            status_code=503,
            detail="flagship controller is not configured",
        )
    request_body = body or FlagshipRequest()
    if os.environ.get("APP_ENV") == "production" and request_body.stale_block_enabled:
        # Defence-in-depth: refuse a deterministic stale-block injection
        # on the production wire, even if a caller sends stale_block_enabled: true.
        # The underlying helper raises RuntimeError under APP_ENV=production,
        # but reject it at the boundary instead of round-tripping to the helper.
        request_body = request_body.model_copy(update={"stale_block_enabled": False})
        log.warning("flagship.start.production_stale_block_refused correlation_id=%s", request_body.correlation_id)
    try:
        result = await controller.start(request_body)
    except FlagshipStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize(result)


@router.get("/status")
def status_route(request: Request) -> dict[str, Any]:
    """Return the current flagship phase and the last completed run."""

    controller = _controller(request)
    if not controller.is_configured:
        raise HTTPException(
            status_code=503,
            detail="flagship controller is not configured",
        )
    return _serialize(controller.status())


def _serialize(value: Any) -> dict[str, Any]:
    """Convert the dataclasses into JSON-friendly dictionaries."""

    from dataclasses import asdict, is_dataclass

    if is_dataclass(value):
        return asdict(value)  # type: ignore[arg-type]
    return value  # type: ignore[return-value]


def register_routes(app: Any) -> None:
    """Attach the flagship router to a FastAPI app instance.

    Called from ``main.create_app`` after the controller has been registered
    on ``app.state.flagship_controller``.
    """
    app.include_router(router)
