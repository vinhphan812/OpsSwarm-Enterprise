"""Provider-neutral, deterministic Simulation/Candidate read repository."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from retailtwin_api.simulation_schemas import (
    AgentActivityEntry,
    CandidateListResponse,
    CursorParameters,
    PageParameters,
    SimulationCandidateResponse,
    SimulationDetail,
    SimulationFilters,
    SimulationListResponse,
    SimulationSummary,
)


class SimulationReadRepository(Protocol):
    """Provider-neutral contract implemented by memory and future Firestore adapters."""

    @property
    def available(self) -> bool: ...  # pragma: no branch

    def list_simulations(self, filters: SimulationFilters) -> SimulationListResponse: ...  # pragma: no branch

    def get_simulation(self, simulation_id: str) -> SimulationDetail | None: ...  # pragma: no branch

    def list_candidates(
        self, simulation_id: str, page: PageParameters
    ) -> CandidateListResponse | None: ...  # pragma: no branch

    def list_agent_events(self, cursor: CursorParameters) -> tuple[list[AgentActivityEntry], str | None]: ...  # pragma: no branch


class InMemorySimulationRepository:
    """Explicit development/test adapter, never loaded as an implicit production fixture."""

    def __init__(
        self,
        simulations: Iterable[SimulationDetail] = (),
        candidates: Iterable[SimulationCandidateResponse] = (),
        agent_events: Iterable[AgentActivityEntry] = (),
        available: bool = True,
    ) -> None:
        self._available = available
        self._lock = threading.RLock()
        self._simulations = {item.simulation_id: item.model_copy(deep=True) for item in simulations}
        self._candidates: dict[str, list[SimulationCandidateResponse]] = {}
        for item in candidates:
            self._candidates.setdefault(item.simulation_id, []).append(item.model_copy(deep=True))
        self._agent_events = sorted(
            (item.model_copy(deep=True) for item in agent_events),
            key=lambda item: (item.ts, item.id),
        )

    @property
    def available(self) -> bool:
        return self._available

    def list_simulations(self, filters: SimulationFilters) -> SimulationListResponse:
        with self._lock:
            items = list(self._simulations.values())
            if filters.store_id is not None:
                items = [item for item in items if item.store_id == filters.store_id]
            if filters.status == "open":
                items = [item for item in items if item.status in ("pending", "evaluated")]
            elif filters.status is not None:
                items = [item for item in items if item.status == filters.status]
            items.sort(key=lambda item: (item.updated_at, item.simulation_id), reverse=True)
            total = len(items)
            start = (filters.page - 1) * filters.page_size
            window = items[start : start + filters.page_size]
            next_cursor = str(filters.page + 1) if start + filters.page_size < total else None
            return SimulationListResponse(
                simulations=[
                    SimulationSummary(
                        simulation_id=item.simulation_id,
                        store_id=item.store_id,
                        base_context_version=item.base_context_version,
                        status=item.status,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                        provenance=item.provenance,
                    )
                    for item in window
                ],
                page=filters.page,
                page_size=filters.page_size,
                total=total,
                next_cursor=next_cursor,
            )

    def get_simulation(self, simulation_id: str) -> SimulationDetail | None:
        with self._lock:
            item = self._simulations.get(simulation_id)
            return item.model_copy(deep=True) if item is not None else None

    def list_candidates(self, simulation_id: str, page: PageParameters) -> CandidateListResponse | None:
        with self._lock:
            if simulation_id not in self._simulations:
                return None
            all_items = self._candidates.get(simulation_id, [])
            total = len(all_items)
            start = (page.page - 1) * page.page_size
            window = all_items[start : start + page.page_size]
            next_cursor = str(page.page + 1) if start + page.page_size < total else None
            return CandidateListResponse(
                candidates=[item.model_copy(deep=True) for item in window],
                page=page.page,
                page_size=page.page_size,
                total=total,
                next_cursor=next_cursor,
            )

    def list_agent_events(self, cursor: CursorParameters) -> tuple[list[AgentActivityEntry], str | None]:
        with self._lock:
            start = 0
            if cursor.since is not None:
                try:
                    start = int(cursor.since)
                except ValueError:
                    raise ValueError(f"Invalid cursor value {cursor.since!r}: must be a non-negative integer.") from None
                if start < 0:
                    raise ValueError(f"Invalid cursor value {cursor.since!r}: must be a non-negative integer.") from None
            window = self._agent_events[start : start + cursor.limit]
            offset = start + len(window)
            next_cursor = str(offset) if offset < len(self._agent_events) else None
            return [item.model_copy(deep=True) for item in window], next_cursor


def unavailable_simulation_repository() -> SimulationReadRepository:
    return InMemorySimulationRepository(available=False)
