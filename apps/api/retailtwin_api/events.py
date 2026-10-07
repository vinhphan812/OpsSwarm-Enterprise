"""In-process event intake. Accepting an event does not change inventory."""

import threading

from retailtwin_api.schemas import StoreEvent


class EventLog:
    def __init__(self) -> None:
        self._events: dict[str, StoreEvent] = {}
        self._lock = threading.Lock()

    def accept(self, event: StoreEvent) -> tuple[StoreEvent, bool]:
        with self._lock:
            existing = self._events.get(event.event_id)
            if existing is not None:
                return existing, True
            stored = event.model_copy(deep=True)
            self._events[event.event_id] = stored
            return stored, False
