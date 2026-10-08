"""In-process event intake. An event id names one immutable payload."""

import threading

from retailtwin_api.schemas import StoreEvent


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
