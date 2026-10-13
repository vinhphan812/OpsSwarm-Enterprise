"""In-process event intake. An event id names one immutable payload."""

import threading
from datetime import datetime, timezone

from retailtwin_api.schemas import StoreEvent
from retailtwin_api.simulation_schemas import (
    DecisionReviewReasonCode,
    DecisionReviewVerdict,
    ReviewAuditRecord,
)


class EventConflict(Exception):
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(event_id)


class EventLog:
    def __init__(self) -> None:
        self._events: dict[str, StoreEvent] = {}
        self._lock = threading.Lock()

    def get(self, event_id: str) -> StoreEvent | None:
        with self._lock:
            existing = self._events.get(event_id)
            if existing is None:
                return None
            return existing.model_copy(deep=True)

    def accept(self, event: StoreEvent) -> tuple[StoreEvent, bool]:
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is not None:
                if existing == event:
                    return existing.model_copy(deep=True), True
                raise EventConflict(event.event_id)
            stored = event.model_copy(deep=True)
            self._events[event.event_id] = stored
            return stored, False


class ReviewAuditLog:
    """Immutable append-only audit log for simulation review decisions."""

    def __init__(self) -> None:
        self._records: list[ReviewAuditRecord] = []
        self._lock = threading.Lock()

    def record(
        self,
        simulation_id: str,
        decision: str,
        base_context_version: str,
        proposal_context_version: str,
        live_context_version: str,
        verdict: DecisionReviewVerdict,
        reason_code: DecisionReviewReasonCode,
    ) -> ReviewAuditRecord:
        record = ReviewAuditRecord(
            simulation_id=simulation_id,
            decision=decision,  # type: ignore[arg-type]
            base_context_version=base_context_version,
            proposal_context_version=proposal_context_version,
            live_context_version=live_context_version,
            verdict=verdict,
            reason_code=reason_code,
            recorded_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._records.append(record)
        return record

    def get(self, simulation_id: str) -> list[ReviewAuditRecord]:
        with self._lock:
            return [r for r in self._records if r.simulation_id == simulation_id]
