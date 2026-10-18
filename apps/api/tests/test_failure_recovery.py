"""Tests for the typed failure recovery layer (ADR 0024, issue #217)."""

from __future__ import annotations

import pytest

from retailtwin_api.failure_recovery import (
    BadEventPayload,
    DuplicateEvent,
    FailureResolution,
    InsufficientEvidence,
    LlmProviderFailed,
    ProcessRestart,
    STATUS_BAD_PAYLOAD,
    STATUS_DUPLICATE_EVENT,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_PROCESS_RESTART,
    STATUS_PROVIDER_FAILED,
    STATUS_STALE_PLAN,
    StalePlan,
    resolve_failure,
)


class TestResolveFailure:
    @pytest.mark.parametrize(
        "exc_cls,expected_status",
        [
            (BadEventPayload, STATUS_BAD_PAYLOAD),
            (InsufficientEvidence, STATUS_INSUFFICIENT_EVIDENCE),
            (LlmProviderFailed, STATUS_PROVIDER_FAILED),
            (StalePlan, STATUS_STALE_PLAN),
            (DuplicateEvent, STATUS_DUPLICATE_EVENT),
            (ProcessRestart, STATUS_PROCESS_RESTART),
        ],
    )
    def test_known_exception_maps_to_typed_status(
        self, exc_cls: type[Exception], expected_status: str
    ) -> None:
        resolution = resolve_failure(exc_cls("test"))
        assert resolution.status == expected_status
        assert isinstance(resolution, FailureResolution)

    def test_bad_payload_does_not_requeue(self) -> None:
        resolution = resolve_failure(BadEventPayload("test"))
        assert resolution.requeue is False

    def test_provider_failed_requeues(self) -> None:
        # A Vertex outage must leave the Pub/Sub message unacked so the
        # next delivery retries after the outage clears.
        resolution = resolve_failure(LlmProviderFailed("test"))
        assert resolution.requeue is True

    def test_process_restart_requeues(self) -> None:
        # Durable adapters recover state on the next delivery; the consumer
        # must leave the message unacked.
        resolution = resolve_failure(ProcessRestart("test"))
        assert resolution.requeue is True

    def test_insufficient_evidence_does_not_requeue(self) -> None:
        resolution = resolve_failure(InsufficientEvidence("test"))
        assert resolution.requeue is False

    def test_stale_plan_does_not_requeue(self) -> None:
        resolution = resolve_failure(StalePlan("test"))
        assert resolution.requeue is False

    def test_duplicate_event_does_not_requeue(self) -> None:
        resolution = resolve_failure(DuplicateEvent("test"))
        assert resolution.requeue is False

    def test_unknown_exception_defaults_to_provider_failed(self) -> None:
        # An unrecognised exception is treated as a transient provider
        # outage so Pub/Sub re-delivers rather than silently dropping it.
        resolution = resolve_failure(RuntimeError("boom"))
        assert resolution.status == STATUS_PROVIDER_FAILED
        assert resolution.requeue is True