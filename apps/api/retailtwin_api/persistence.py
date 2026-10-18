"""Composition root for durable agent state (ADR 0024).

Selects the process-memory or Firestore-backed adapters that back
``DecisionSource``, ``SimulationReadRepository``, ``AgentActivityLog`` and
``MemoryActivationLedger``. The factory is the single place that decides
which storage backend a Cloud Run instance uses; the lifespan wires the
returned adapters into ``app.state`` once at startup.

Selection rule
--------------
``LIVE_TWIN_BACKEND``:

* ``"fixture"`` — read-only day-0 fixture; no Decisions are stored. The
  ``decisions`` adapter is the unavailable one, the routes return 503.
* ``"memory"`` — in-process adapters for tests and local dev.
* ``"firestore"`` — Firestore-backed durable adapters. The same project
  as the Live Twin (``retailtwin-ai-511002``).

Production (``APP_ENV=production``) is fail-closed: an unknown or missing
``LIVE_TWIN_BACKEND`` raises ``ValueError`` instead of silently falling
back to in-process memory. This prevents a misconfigured Cloud Run
revision from losing agent state across a deploy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from retailtwin_api.agents.observer.consumer import MemoryActivationLedger
from retailtwin_api.decisions import DecisionSource, InMemoryDecisionSource
from retailtwin_api.firestore_activation_ledger import FirestoreActivationLedger
from retailtwin_api.firestore_agent_activity import FirestoreAgentActivityLog
from retailtwin_api.firestore_decisions import FirestoreDecisionSource
from retailtwin_api.firestore_simulations import FirestoreSimulationRepository
from retailtwin_api.settings import Settings
from retailtwin_api.simulation_repository import SimulationReadRepository

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DurableAdapters:
    """Bundle of cross-instance adapters returned by :func:`get_persistence`."""

    decisions: DecisionSource
    simulations: SimulationReadRepository
    activity: Any  # AgentActivityLog — typed as Any to avoid the import cycle
    activation_ledger: MemoryActivationLedger


class _UnavailableDecisionSourceAdapter:
    """Adapter shaped like :class:`DecisionSource` that returns ``available=False``.

    A read returns ``None``; a write raises :class:`RuntimeError` so a chain
    that runs against the fixture backend cannot accidentally mutate state
    that does not exist.
    """

    @property
    def available(self) -> bool:
        return False

    def put(self, simulation_id: str, decision) -> None:  # noqa: D401 — typed boundary
        raise RuntimeError(
            "Cannot persist Decision in fixture backend: LIVE_TWIN_BACKEND=fixture is read-only."
        )

    def get_for_simulation(self, simulation_id: str):  # noqa: D401 — typed boundary
        return None


def _unavailable_decisions_source() -> DecisionSource:
    return _UnavailableDecisionSourceAdapter()  # type: ignore[return-value]


def _unavailable_simulations_source() -> SimulationReadRepository:
    """Read-only simulation repository used when LIVE_TWIN_BACKEND=fixture."""

    class _Unavailable(SimulationReadRepository):
        @property
        def available(self) -> bool:
            return False

        def list_simulations(self, filters):  # noqa: D401 — typed boundary
            from retailtwin_api.simulation_schemas import (
                SimulationListResponse,
            )

            return SimulationListResponse(
                simulations=[],
                page=filters.page,
                page_size=filters.page_size,
                total=0,
                next_cursor=None,
            )

        def get_simulation(self, simulation_id):
            return None

        def list_candidates(self, simulation_id, page):
            return None

        def list_agent_events(self, cursor):
            return [], None

        def set_status(self, simulation_id, status, at):
            return None

    return _Unavailable()


def get_persistence(
    settings: Settings,
    *,
    store_view_fn: Callable[[], Any] | None = None,
    activity: Any | None = None,
) -> DurableAdapters:
    """Build the cross-instance adapter bundle for the configured backend.

    The ``memory`` backend needs a live ``store_view_fn`` (and an optional
    ``activity`` sink) so the seeded simulation matches the same Live view the
    rest of the API serves. The Firestore backend needs neither because the
    ``SimulationDetail`` payload is self-contained.

    Returns the same Protocol objects regardless of backend, so the rest of
    the code is agnostic. The factory logs the chosen backend so a
    misconfigured Cloud Run revision surfaces in the startup log.
    """
    backend = settings.live_twin_backend
    # fail-closed: production may only use firestore. Any other value (including
    # memory and fixture) must raise before building in-process state that would
    # be lost on the next Cloud Run deploy.
    if settings.is_production and backend != "firestore":
        raise ValueError(
            f"LIVE_TWIN_BACKEND={backend!r} is not supported in production. "
            "Set LIVE_TWIN_BACKEND=firestore explicitly. "
            "Supported production value: 'firestore'."
        )
    if backend == "firestore":
        log.info(
            "persistence.firestore project=%s",
            settings.google_cloud_project or "retailtwin-ai-511002",
        )
        from retailtwin_api.agent_activity import AgentActivityLog

        # Use the activity instance the caller already built so the in-memory
        # ``SimulationRepository`` mirror (if any) shares the same feed.
        activity_log = activity if activity is not None else AgentActivityLog()
        return DurableAdapters(
            decisions=FirestoreDecisionSource(),
            simulations=FirestoreSimulationRepository(),
            activity=FirestoreAgentActivityLog(),
            activation_ledger=FirestoreActivationLedger(),
        )
    if backend == "fixture":
        log.warning(
            "persistence.fixture_read_only store_id=%s",
            settings.store_id,
        )
        from retailtwin_api.agent_activity import AgentActivityLog

        activity_log = activity if activity is not None else AgentActivityLog()
        return DurableAdapters(
            decisions=_unavailable_decisions_source(),
            simulations=_unavailable_simulations_source(),
            activity=activity_log,
            activation_ledger=MemoryActivationLedger(),
        )
    if backend == "memory":
        log.info("persistence.memory store_id=%s", settings.store_id)
        if store_view_fn is None:
            raise ValueError(
                "memory backend requires a store_view_fn so the seeded "
                "simulation matches the Live view."
            )
        from retailtwin_api.agent_activity import AgentActivityLog
        from retailtwin_api.simulation import SimulationRepository

        activity_log = activity if activity is not None else AgentActivityLog()
        simulations = SimulationRepository(
            store_view_fn,
            settings.store_id,
            activity=activity_log,
        )
        return DurableAdapters(
            decisions=InMemoryDecisionSource(),
            simulations=simulations,
            activity=activity_log,
            activation_ledger=MemoryActivationLedger(),
        )
    # fail-closed: production must never silently fall back to memory.
    if settings.is_production:
        raise ValueError(
            f"LIVE_TWIN_BACKEND={backend!r} is not supported in production. "
            "Set LIVE_TWIN_BACKEND=firestore explicitly. "
            "Supported production value: 'firestore'."
        )
    log.warning(
        "persistence.unknown_backend backend=%r store_id=%s",
        backend,
        settings.store_id,
    )
    raise ValueError(f"Unknown LIVE_TWIN_BACKEND {backend!r}. Supported values: 'fixture', 'memory', 'firestore'.")


__all__ = ["DurableAdapters", "get_persistence"]