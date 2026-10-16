"""Handoff between the observer consumer and the FlagshipController.

The observer consumer is synchronous; the FlagshipController's
``start_for_event`` coroutine is async. This module owns that sync/async
boundary.

The ``FlagshipInvestigationStarter`` is constructed at lifespan time with a
``controller_getter`` that returns the process-wide ``FlagshipController``
(or ``None`` if wiring failed). When the observer hands it an
``InvestigationStart``, the adapter:

1. looks up the controller;
2. refuses the handoff with ``ObservationError`` if the controller is missing
   or not configured — the consumer does not ack the message and Pub/Sub
   re-delivers it;
3. drives ``controller.start_for_event(start.event)`` in a fresh
   ``asyncio.run`` loop, because the consumer itself is sync (it runs in a
   worker thread via ``asyncio.to_thread`` or a dedicated daemon thread).

Production safety (ADR 0023 — autonomous event path):

* the Live Twin is **not** reset — a real sale must investigate the current
  store state, not a freshly seeded demo baseline;
* the canonical deterministic ``stale_block_enabled=True`` injection is
  never used — real events go through the controller's normal guard and
  replan chain without a deliberate ``REFRESH_REQUIRED`` race.

No model SDK is imported here. The starter only knows about the controller's
public command surface.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from retailtwin_api.agents.observer.consumer import (
    InvestigationStart,
    ObservationError,
)
from retailtwin_api.flagship.controller import FlagshipController

log = logging.getLogger(__name__)


class FlagshipInvestigationStarter:
    """Adapter that hands an ``InvestigationStart`` to the FlagshipController.

    Boundary: this class is the only place in the agent tree that synchronously
    blocks on an async run. The controller is responsible for every step after
    the handoff (investigate → plan → simulate → guard → commit → verify).
    """

    def __init__(
        self,
        controller_getter: Callable[[], FlagshipController | None],
    ) -> None:
        self._controller_getter = controller_getter

    def _lookup_controller(self, start: InvestigationStart) -> FlagshipController:
        controller = self._controller_getter()
        if controller is None or not controller.is_configured:
            log.warning(
                "flagship.handoff_refused event_id=%s correlation_id=%s reason=not_configured",
                start.event.event_id,
                start.event.correlation_id,
            )
            raise ObservationError(start.event.event_id)
        return controller

    def start_investigation_for_event(self, start: InvestigationStart) -> None:
        """Drive one flagship run for a real incoming ``start.event``.

        Production autonomous path (ADR 0023). Does NOT reset the Live Twin
        and does NOT trigger the deterministic stale-block injection — those
        knobs are reserved for the explicit demo /flagship/start flow.
        The real event content (``event_id``, ``sku``, ``quantity``,
        ``occurred_at``, ``store_id``, ``correlation_id``) is preserved
        end-to-end.

        Raises :class:`ObservationError` when the controller is not
        configured — the consumer treats that as a non-terminal outcome
        and the message is left unacked so Pub/Sub re-delivers it after
        the wiring failure is fixed. Exceptions raised by the controller
        propagate; the consumer wraps them in :class:`ObservationError`
        and aborts the activation ledger reservation.
        """
        controller = self._lookup_controller(start)
        asyncio.run(
            controller.start_for_event(
                start.event,
                correlation_id=start.event.correlation_id,
            )
        )

    # Backwards-compatible alias for tests that exercise the older reset +
    # start() handoff. Production code MUST NOT use this — the reset
    # clobbers the Live Twin and is reserved for the demo /flagship/start
    # path. New callers should use ``start_investigation_for_event``.
    def start_investigation(self, start: InvestigationStart) -> None:
        """Drive one flagship run via the demo ``reset`` + ``start`` path.

        .. deprecated::
            Production autonomous events must use
            :meth:`start_investigation_for_event`. This method resets the
            Live Twin and is only kept for unit tests that exercise the
            demo orchestration. Will be removed once the demo contract
            migrates to ``POST /flagship/start`` directly.
        """
        controller = self._lookup_controller(start)
        controller.reset()
        from retailtwin_api.flagship.controller import FlagshipRequest
        flags = FlagshipRequest(correlation_id=start.event.correlation_id)
        asyncio.run(controller.start(flags))


__all__ = ["FlagshipInvestigationStarter"]