"""Twin Service — in-memory MVP for the Digital Twin.

Owns access to current store state. Canonical hierarchy:
Store -> Zone -> Shelf -> Slot -> Product

This is an in-memory implementation for the MVP demo. It uses the existing
StoreRepository fixture from apps/api/retailtwin_api/store.py.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class SlotState:
    """Current state of one slot in the store."""
    slot_id: str
    sku: str
    facings: int
    shelf_quantity: int
    backroom_quantity: int


@dataclass
class StoreState:
    """Complete read-only snapshot of the live store."""
    store_id: str
    version: str  # monotonic version string
    context_version: str  # stable context identifier
    slots: dict[str, SlotState] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_slot(self, slot_id: str) -> SlotState | None:
        return self.slots.get(slot_id)

    def get_sku(self, sku: str) -> list[SlotState]:
        return [s for s in self.slots.values() if s.sku == sku]


class TwinService:
    """In-memory Digital Twin with thread-safe state management.

    Core invariant: every mutation increments the version.
    The twin never mutates directly — mutations come from authorized actions.
    """

    def __init__(self, store_id: str = "store-001") -> None:
        self._store_id = store_id
        self._lock = threading.RLock()
        self._version = 0
        self._context_version = str(uuid.uuid4())
        self._slots: dict[str, SlotState] = {}

    # -------------------------------------------------------------------------
    # Version & context
    # -------------------------------------------------------------------------

    def get_version(self) -> str:
        """Monotonically increasing version string."""
        with self._lock:
            return str(self._version)

    def get_context_version(self) -> str:
        """Stable context identifier — changes on reset."""
        with self._lock:
            return self._context_version

    def get_context_timestamp(self) -> datetime:
        """UTC timestamp of the current context."""
        with self._lock:
            return datetime.now(timezone.utc)

    # -------------------------------------------------------------------------
    # State access
    # -------------------------------------------------------------------------

    def read(self) -> StoreState:
        """Return a read-only snapshot of current store state."""
        with self._lock:
            return StoreState(
                store_id=self._store_id,
                version=str(self._version),
                context_version=self._context_version,
                slots=dict(self._slots),
            )

    def read_slot(self, slot_id: str) -> SlotState | None:
        """Read a single slot."""
        with self._lock:
            return self._slots.get(slot_id)

    def read_sku(self, sku: str) -> list[SlotState]:
        """Read all slots containing a given SKU."""
        with self._lock:
            return [s for s in self._slots.values() if s.sku == sku]

    # -------------------------------------------------------------------------
    # State mutation (only via authorized actions)
    # -------------------------------------------------------------------------

    def apply_facings(self, slot_id: str, facings: int) -> None:
        """Set the number of facings for a slot. Only called by Executor."""
        with self._lock:
            if slot_id not in self._slots:
                raise KeyError(f"Slot {slot_id} does not exist")
            slot = self._slots[slot_id]
            self._slots[slot_id] = SlotState(
                slot_id=slot.slot_id,
                sku=slot.sku,
                facings=facings,
                shelf_quantity=slot.shelf_quantity,
                backroom_quantity=slot.backroom_quantity,
            )
            self._version += 1

    def apply_replenish(self, slot_id: str, quantity: int) -> None:
        """Add quantity to shelf. Only called by Executor."""
        with self._lock:
            if slot_id not in self._slots:
                raise KeyError(f"Slot {slot_id} does not exist")
            slot = self._slots[slot_id]
            self._slots[slot_id] = SlotState(
                slot_id=slot.slot_id,
                sku=slot.sku,
                facings=slot.facings,
                shelf_quantity=slot.shelf_quantity + quantity,
                backroom_quantity=slot.backroom_quantity,
            )
            self._version += 1

    def apply_move(
        self, from_slot_id: str, to_slot_id: str, quantity: int
    ) -> None:
        """Move quantity between slots. Only called by Executor."""
        with self._lock:
            if from_slot_id not in self._slots or to_slot_id not in self._slots:
                raise KeyError("Slot not found")
            from_slot = self._slots[from_slot_id]
            to_slot = self._slots[to_slot_id]
            self._slots[from_slot_id] = SlotState(
                slot_id=from_slot.slot_id,
                sku=from_slot.sku,
                facings=from_slot.facings,
                shelf_quantity=from_slot.shelf_quantity - quantity,
                backroom_quantity=from_slot.backroom_quantity,
            )
            self._slots[to_slot_id] = SlotState(
                slot_id=to_slot.slot_id,
                sku=to_slot.sku,
                facings=to_slot.facings,
                shelf_quantity=to_slot.shelf_quantity + quantity,
                backroom_quantity=to_slot.backroom_quantity,
            )
            self._version += 1

    # -------------------------------------------------------------------------
    # Reset (for demo controller)
    # -------------------------------------------------------------------------

    def reset(self, fixtures: list[dict]) -> None:
        """Reset to initial fixture state. Increments context_version."""
        with self._lock:
            self._slots.clear()
            for f in fixtures:
                self._slots[f["slot_id"]] = SlotState(
                    slot_id=f["slot_id"],
                    sku=f["sku"],
                    facings=f["facings"],
                    shelf_quantity=f["shelf_quantity"],
                    backroom_quantity=f["backroom_quantity"],
                )
            self._version = 0
            self._context_version = str(uuid.uuid4())

    def load_from_store(self, products: list[dict]) -> None:
        """Load state from a list of ProductInventory-like dicts (from API)."""
        with self._lock:
            self._slots.clear()
            for p in products:
                self._slots[p["slot_id"]] = SlotState(
                    slot_id=p["slot_id"],
                    sku=p["sku"],
                    facings=p["facings"],
                    shelf_quantity=p["shelf_quantity"],
                    backroom_quantity=p["backroom_quantity"],
                )
            self._version = 0
            self._context_version = str(uuid.uuid4())
