"""Simulation Service — clone/apply/evaluate for the Digital Twin.

Clones live state into a simulation branch, applies candidate actions,
and calculates before/after KPIs.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from retailtwin_api.demo_runtime.services.twin import SlotState, StoreState, TwinService

if TYPE_CHECKING:
    pass


@dataclass
class SimulationSnapshot:
    """Frozen copy of store state for simulation."""
    slots: dict[str, SlotState] = field(default_factory=dict)

    def copy_slot(self, slot_id: str) -> SlotState | None:
        s = self.slots.get(slot_id)
        if s is None:
            return None
        return SlotState(
            slot_id=s.slot_id,
            sku=s.sku,
            facings=s.facings,
            shelf_quantity=s.shelf_quantity,
            backroom_quantity=s.backroom_quantity,
        )


@dataclass
class SimResult:
    """Result of applying actions to a simulation snapshot."""
    slot_id: str
    action_type: str  # "facings" | "replenish" | "move"
    before: dict
    after: dict
    version_delta: int  # how many times version incremented


@dataclass
class SimulationKPIResult:
    """Before/after KPI comparison for a simulation run."""
    total_shelf_quantity: int
    total_facings: int
    sku_facings: dict[str, int]  # sku -> total facings
    sku_shelf: dict[str, int]  # sku -> total shelf quantity
    gap_score: float  # higher = more inventory imbalance


class SimulationService:
    """Clone-and-simulate engine for the Digital Twin.

    Thread-safe simulation branches — each clone is independent.
    """

    def __init__(self, twin: TwinService) -> None:
        self._twin = twin
        self._lock = threading.Lock()

    def clone(self) -> SimulationSnapshot:
        """Clone current live state into a simulation snapshot."""
        with self._lock:
            state = self._twin.read()
            snap = SimulationSnapshot(slots=dict(state.slots))
            return snap

    def apply(
        self, snapshot: SimulationSnapshot, actions: list[dict]
    ) -> list[SimResult]:
        """Apply actions to a simulation snapshot and return results."""
        results = []
        for action in actions:
            atype = action.get("action_type", "")
            slot_id = action.get("slot_id", "")
            slot = snapshot.copy_slot(slot_id)

            if slot is None:
                results.append(
                    SimResult(
                        slot_id=slot_id,
                        action_type=atype,
                        before={},
                        after={},
                        version_delta=0,
                    )
                )
                continue

            before = {
                "facings": slot.facings,
                "shelf_quantity": slot.shelf_quantity,
            }

            if atype == "facings":
                new_facings = action.get("facings", slot.facings)
                snapshot.slots[slot_id] = SlotState(
                    slot_id=slot.slot_id,
                    sku=slot.sku,
                    facings=new_facings,
                    shelf_quantity=slot.shelf_quantity,
                    backroom_quantity=slot.backroom_quantity,
                )
            elif atype == "replenish":
                qty = action.get("quantity", 0)
                snapshot.slots[slot_id] = SlotState(
                    slot_id=slot.slot_id,
                    sku=slot.sku,
                    facings=slot.facings,
                    shelf_quantity=slot.shelf_quantity + qty,
                    backroom_quantity=slot.backroom_quantity,
                )
            elif atype == "move":
                from_id = action.get("from_slot_id", "")
                to_id = action.get("to_slot_id", "")
                qty = action.get("quantity", 0)
                from_slot = snapshot.copy_slot(from_id)
                to_slot = snapshot.copy_slot(to_id)
                if from_slot and to_slot:
                    snapshot.slots[from_id] = SlotState(
                        slot_id=from_slot.slot_id,
                        sku=from_slot.sku,
                        facings=from_slot.facings,
                        shelf_quantity=from_slot.shelf_quantity - qty,
                        backroom_quantity=from_slot.backroom_quantity,
                    )
                    snapshot.slots[to_id] = SlotState(
                        slot_id=to_slot.slot_id,
                        sku=to_slot.sku,
                        facings=to_slot.facings,
                        shelf_quantity=to_slot.shelf_quantity + qty,
                        backroom_quantity=to_slot.backroom_quantity,
                    )

            after = {
                "facings": snapshot.slots[slot_id].facings,
                "shelf_quantity": snapshot.slots[slot_id].shelf_quantity,
            }

            results.append(
                SimResult(
                    slot_id=slot_id,
                    action_type=atype,
                    before=before,
                    after=after,
                    version_delta=1,
                )
            )

        return results

    def evaluate(self, snapshot: SimulationSnapshot) -> SimulationKPIResult:
        """Evaluate KPIs for a simulation snapshot."""
        total_shelf = 0
        total_facings = 0
        sku_facings: dict[str, int] = {}
        sku_shelf: dict[str, int] = {}

        for slot in snapshot.slots.values():
            total_shelf += slot.shelf_quantity
            total_facings += slot.facings
            sku_facings[slot.sku] = sku_facings.get(slot.sku, 0) + slot.facings
            sku_shelf[slot.sku] = sku_shelf.get(slot.sku, 0) + slot.shelf_quantity

        # Gap score: variance in shelf quantities as proxy for imbalance
        if len(sku_shelf) > 1:
            vals = list(sku_shelf.values())
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            gap_score = variance / max(mean, 1)
        else:
            gap_score = 0.0

        return SimulationKPIResult(
            total_shelf_quantity=total_shelf,
            total_facings=total_facings,
            sku_facings=sku_facings,
            sku_shelf=sku_shelf,
            gap_score=gap_score,
        )
