"""Append-only Agent Activity feed behind ``GET /agent/events``.

Each entry is a lifecycle fact (stage, status, ids, a short summary). No model
reasoning is stored. The cursor is the offset of the next entry.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from retailtwin_api.contracts import ControlStage
from retailtwin_api.simulation_schemas import AgentActivityEntry, CursorParameters


class AgentActivityLog:
    """Process-memory activity feed, in record order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[AgentActivityEntry] = []

    def record(
        self,
        stage: ControlStage,
        status: str,
        correlation_id: str,
        *,
        run_id: str | None = None,
        decision: str | None = None,
        simulation_id: str | None = None,
        sku: str | None = None,
        shelf_id: str | None = None,
        slot_id: str | None = None,
        summary: str | None = None,
        at: datetime | None = None,
    ) -> AgentActivityEntry:
        entry = AgentActivityEntry(
            id=f"act-{uuid.uuid4().hex[:12]}",
            ts=at or datetime.now(timezone.utc),
            stage=stage,
            status=status,
            correlation_id=correlation_id,
            run_id=run_id,
            decision=decision,
            simulation_id=simulation_id,
            sku=sku,
            shelf_id=shelf_id,
            slot_id=slot_id,
            focus=sku,
            summary=summary,
        )
        with self._lock:
            self._entries.append(entry)
        return entry.model_copy(deep=True)

    def page(self, cursor: CursorParameters) -> tuple[list[AgentActivityEntry], str | None]:
        start = 0
        if cursor.since is not None:
            try:
                start = int(cursor.since)
            except ValueError:
                raise ValueError(f"Invalid cursor value {cursor.since!r}: must be a non-negative integer.") from None
            if start < 0:
                raise ValueError(f"Invalid cursor value {cursor.since!r}: must be a non-negative integer.")
        with self._lock:
            window = self._entries[start : start + cursor.limit]
            offset = start + len(window)
            next_cursor = str(offset) if offset < len(self._entries) else None
            return [item.model_copy(deep=True) for item in window], next_cursor

    def for_correlation(self, correlation_id: str) -> list[AgentActivityEntry]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._entries if e.correlation_id == correlation_id]
