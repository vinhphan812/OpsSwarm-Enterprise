"""In-memory Simulation Twin, backed by the store fixture.

This is not the Live Twin. It starts from the store's current view and applies
proposed actions to produce a simulated state. The store stays unchanged.

Once the Simulation Service (A07) and KPI evaluator (D11) are wired in, this
module becomes the adapter that calls them — the routes and the response contracts
stay the same.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from retailtwin_api.contracts import ActionUnion, ChangeFacings, MoveProduct, ReplenishShelf
from retailtwin_api.schemas import ProductInventory, StoreResponse
from retailtwin_api.simulation_repository import SimulationFilters, SimulationListResponse
from retailtwin_api.simulation_schemas import (
    SimulationDetail as SimulationDetailSchema,
    SimulationState,
    SimulationStatus,
    SimulationSummary as SimulationSummarySchema,
)


# ─── Seed actions (internal) ─────────────────────────────────────────────────

SEED_ACTIONS: list[ActionUnion] = [
    MoveProduct(sku="P001", from_slot="A01-S01", to_slot="A01-S02"),
    ChangeFacings(sku="P001", facings=5),
]


# ─── Helpers ────────────────────────────────────────────────────────────────

_HOLDER_RE = re.compile(r"^(?P<holder>.+)-\w+$")


def _holder_of(slot_id: str) -> str:
    m = _HOLDER_RE.match(slot_id)
    return m.group("holder") if m else slot_id.rsplit("-", 1)[0]


def _apply(product: ProductInventory, action: ActionUnion) -> ProductInventory:
    if isinstance(action, ReplenishShelf):
        qty = min(action.quantity, product.backroom_quantity)
        return product.model_copy(
            update={
                "shelf_quantity": product.shelf_quantity + qty,
                "backroom_quantity": product.backroom_quantity - qty,
            }
        )
    elif isinstance(action, ChangeFacings):
        return product.model_copy(update={"facings": action.facings})
    elif isinstance(action, MoveProduct):
        return product.model_copy(
            update={
                "shelf_id": _holder_of(action.to_slot),
                "slot_id": action.to_slot,
            }
        )
    return product


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_state(
    base: StoreResponse, actions: list[ActionUnion]
) -> SimulationState:
    products = []
    for product in base.products:
        affected = [a for a in actions if a.sku == product.sku]
        p = product
        for a in affected:
            p = _apply(p, a)
        products.append(
            p.model_copy(
                update={"version": product.version + (1 if affected else 0)}
            )
        )
    return SimulationState(
        store=StoreResponse(
            store_id=base.store_id,
            context_version=f"{base.context_version}+sim:{_stamp()}",
            version=base.version,
            products=products,
        ),
        context_version=f"{base.context_version}+sim:{_stamp()}",
    )


# ─── Seed simulation ─────────────────────────────────────────────────────────

SEED_SIMULATION_ID = "sim-seed-001"


# ─── SimulationRepository ────────────────────────────────────────────────────

class SimulationRepository:
    """In-memory simulation runs.

    Today the simulations are seeded at startup. When A07 / D11 are wired in, this
    class calls them instead of applying in-memory actions.

    If the store fixture is not loaded (fixture unavailable, or Firestore not ready),
    the repository enters a degraded state: list returns empty and get returns None.
    """

    def __init__(self, store_view_fn, store_id: str) -> None:
        self._store_view_fn = store_view_fn
        self._store_id = store_id
        self._runs: dict[str, SimulationDetailSchema] = {}
        self._available = False
        self._seed()

    @property
    def available(self) -> bool:
        return self._available

    def _seed(self) -> None:
        """Seed one open simulation from the store fixture.

        If the store is not loaded yet (fixture missing, Firestore not ready), the
        repository stays degraded — callers get empty results.
        """
        try:
            base = self._store_view_fn()
        except RuntimeError:
            # Store not loaded. The simulation routes will return 503 or empty lists.
            return
        now = datetime.now(timezone.utc)
        try:
            proposed_state = _build_state(base, SEED_ACTIONS)
        except Exception:
            # Fall back to the base state if actions cannot be applied.
            proposed_state = SimulationState(
                store=base,
                context_version=f"{base.context_version}+sim:{_stamp()}",
            )
        self._runs[SEED_SIMULATION_ID] = SimulationDetailSchema(
            simulation_id=SEED_SIMULATION_ID,
            store_id=self._store_id,
            base_context_version=base.context_version,
            status="pending",
            actions=SEED_ACTIONS,
            state=proposed_state,
            created_at=now,
            updated_at=now,
            provenance="seed",
        )
        self._available = True

    # ── read ───────────────────────────────────────────────────────────────

    def list_simulations(self, filters: SimulationFilters) -> SimulationListResponse:
        if not self._available:
            return SimulationListResponse(
                simulations=[],
                page=filters.page,
                page_size=filters.page_size,
                total=0,
                next_cursor=None,
            )
        items = [
            run for run in self._runs.values()
            if (filters.status == "open" and run.status in {"pending", "evaluated"})
            or (filters.status is None)
            or (run.status == filters.status)
        ]
        total = len(items)
        start = (filters.page - 1) * filters.page_size
        window = items[start : start + filters.page_size]
        next_cursor = str(filters.page + 1) if start + filters.page_size < total else None
        return SimulationListResponse(
            simulations=[
                SimulationSummarySchema(
                    simulation_id=run.simulation_id,
                    store_id=run.store_id,
                    base_context_version=run.base_context_version,
                    status=run.status,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                    provenance=run.provenance,
                )
                for run in window
            ],
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            next_cursor=next_cursor,
        )

    def list_open(self) -> list[SimulationSummarySchema]:
        if not self._available:
            return []
        return [
            SimulationSummarySchema(
                simulation_id=run.simulation_id,
                store_id=run.store_id,
                base_context_version=run.base_context_version,
                status=run.status,
                created_at=run.created_at,
                updated_at=run.updated_at,
                provenance=run.provenance,
            )
            for run in self._runs.values()
            if run.status in {"pending", "evaluated"}
        ]

    def get(self, simulation_id: str) -> SimulationDetailSchema | None:
        if not self._available:
            return None
        return self._runs.get(simulation_id)

    def get_simulation(self, simulation_id: str) -> SimulationDetailSchema | None:
        return self.get(simulation_id)

    def set_status(self, simulation_id: str, status: SimulationStatus, at: datetime) -> None:
        run = self._runs.get(simulation_id)
        if run is None:
            raise KeyError(simulation_id)
        self._runs[simulation_id] = run.model_copy(update={"status": status, "updated_at": at})

    def summary(self, simulation_id: str) -> SimulationSummarySchema | None:
        if not self._available:
            return None
        run = self._runs.get(simulation_id)
        if run is None:
            return None
        return SimulationSummarySchema(
            simulation_id=run.simulation_id,
            store_id=run.store_id,
            base_context_version=run.base_context_version,
            status=run.status,
            created_at=run.created_at,
            updated_at=run.updated_at,
            provenance=run.provenance,
        )
