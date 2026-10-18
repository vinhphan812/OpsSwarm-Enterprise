"""Typed failure recovery (ADR 0024, issue #217).

Issue #217 calls out six explicit failure modes that the autonomous
pipeline must handle. Each failure has a typed status code that the
chain records to ``AgentActivityLog`` so the G03 / G02 / G05 gates can
assert on the payload.

The consumer's :func:`observe_message` does not run the chain itself,
so it surfaces the failure mode of the **handoff**: a starter exception
is caught, an activity entry is recorded, and the message is acked so
Pub/Sub does not re-deliver it forever. The chain itself records its
own failure modes inside :mod:`autonomy` and the simulator; this module
only owns the consumer-side typed recovery.

Failure mode
-------------------
Type
Stated activity status
Re-deliver

``bad_payload``
``BadEventPayload``
``failed``
no — message is quarantined

``insufficient_evidence``
``InsufficientEvidence``
``failed``
no — recorded as a typed activity entry

``provider_failed``
``LlmProviderFailed``
``provider_failed``
yes — Vertex outage; Pub/Sub retries on the next delivery

``stale_plan``
``StalePlan``
``stale_plan``
no — replan loop already exhausted; recorded as failed

``duplicate_event``
``DuplicateEvent``
``duplicate``
no — same payload already started

``process_restart``
``ProcessRestart``
``failed``
yes — durable adapters recover state on the next delivery

The ``requeue"`` attribute is the canonical signal for the consumer to
leave the message unacked; ``True`` means re-deliver, ``False`` means
ack. A failure that should not requeue is one where the canonical
artifact already exists (duplicate event) or the failure is terminal
(bad payload, exhausted replan).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# Canonical status codes recorded to the Agent Activity feed.
STATUS_BAD_PAYLOAD = "bad_payload"
STATUS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
STATUS_PROVIDER_FAILED = "provider_failed"
STATUS_STALE_PLAN = "stale_plan"
STATUS_DUPLICATE_EVENT = "duplicate_event"
STATUS_PROCESS_RESTART = "process_restart"

# Aggregate outcome returned by ``observe_message`` (extends the
# consumer's existing ``OutcomeName`` literal).
OutcomeName = Literal[
    "started",
    "duplicate",
    "conflict",
    "ignored",
    "rejected",
    "insufficient_evidence",
    "provider_failed",
    "stale_plan",
    "process_restart",
]


class FailureRecoveryError(Exception):
    """Base class for typed failure recovery exceptions."""


class BadEventPayload(FailureRecoveryError):
    """The Pub/Sub body could not be parsed as a ``StoreEvent``."""


class InsufficientEvidence(FailureRecoveryError):
    """The investigator returned an ``insufficient_evidence`` bundle."""


class LlmProviderFailed(FailureRecoveryError):
    """The configured LLM provider (Vertex Gemini) raised during the chain."""


class StalePlan(FailureRecoveryError):
    """The Decision Context Guard kept rejecting the plan; replan exhausted."""


class DuplicateEvent(FailureRecoveryError):
    """The same event id and payload were already started."""


class ProcessRestart(FailureRecoveryError):
    """The process restarted mid-investigation; the durable ledger recovered state."""


@dataclass(frozen=True)
class FailureResolution:
    """One failure mode's recovery contract."""

    status: str  # one of the STATUS_* constants.
    requeue: bool  # True ⇒ leave the Pub/Sub message unacked.


_RESOLUTIONS: dict[type[FailureRecoveryError], FailureResolution] = {
    BadEventPayload: FailureResolution(STATUS_BAD_PAYLOAD, requeue=False),
    InsufficientEvidence: FailureResolution(STATUS_INSUFFICIENT_EVIDENCE, requeue=False),
    LlmProviderFailed: FailureResolution(STATUS_PROVIDER_FAILED, requeue=True),
    StalePlan: FailureResolution(STATUS_STALE_PLAN, requeue=False),
    DuplicateEvent: FailureResolution(STATUS_DUPLICATE_EVENT, requeue=False),
    ProcessRestart: FailureResolution(STATUS_PROCESS_RESTART, requeue=True),
}


def resolve_failure(exc: BaseException) -> FailureResolution:
    """Look up the recovery contract for ``exc``.

    Returns the typed resolution when ``exc`` is one of the canonical
    failure classes; falls back to ``provider_failed`` with
    ``requeue=True`` for unknown exceptions so the chain never silently
    drops a transient Vertex outage.
    """
    for cls, resolution in _RESOLUTIONS.items():
        if isinstance(exc, cls):
            return resolution
    return FailureResolution(STATUS_PROVIDER_FAILED, requeue=True)


__all__ = [
    "BadEventPayload",
    "DuplicateEvent",
    "FailureRecoveryError",
    "FailureResolution",
    "InsufficientEvidence",
    "LlmProviderFailed",
    "OutcomeName",
    "ProcessRestart",
    "STATUS_BAD_PAYLOAD",
    "STATUS_DUPLICATE_EVENT",
    "STATUS_INSUFFICIENT_EVIDENCE",
    "STATUS_PROCESS_RESTART",
    "STATUS_PROVIDER_FAILED",
    "STATUS_STALE_PLAN",
    "StalePlan",
    "resolve_failure",
]