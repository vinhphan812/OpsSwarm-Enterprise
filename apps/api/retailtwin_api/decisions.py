"""Where the review routes find the Decision behind a simulation.

The planner or orchestrator records the Decision it simulated. The review
route never builds one: no evidence is invented at approval time.
"""

from __future__ import annotations

import threading
from typing import Protocol

from retailtwin_api.contracts import Decision


class DecisionSource(Protocol):
    @property
    def available(self) -> bool: ...  # pragma: no branch

    def get_for_simulation(self, simulation_id: str) -> Decision | None: ...  # pragma: no branch


class InMemoryDecisionSource:
    """Process-memory decisions by simulation id, for development and tests."""

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self._lock = threading.Lock()
        self._by_simulation: dict[str, Decision] = {}

    @property
    def available(self) -> bool:
        return self._available

    def put(self, simulation_id: str, decision: Decision) -> None:
        with self._lock:
            self._by_simulation[simulation_id] = decision.model_copy(deep=True)

    def get_for_simulation(self, simulation_id: str) -> Decision | None:
        with self._lock:
            found = self._by_simulation.get(simulation_id)
            return found.model_copy(deep=True) if found is not None else None


def unavailable_decision_source() -> DecisionSource:
    return InMemoryDecisionSource(available=False)
