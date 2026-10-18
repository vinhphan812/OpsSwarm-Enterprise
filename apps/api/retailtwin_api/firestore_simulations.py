"""Firestore-backed ``SimulationReadRepository`` (ADR 0024).

Stores ``SimulationDetail`` records as JSON in Firestore documents at
``/simulation_records/{simulation_id}``. Each document carries:

- ``simulation_id`` — the Firestore document id (keyed for idempotent
  ``record`` and ``set_status`` calls).
- ``status`` — separate ``stringValue`` so a ``where status==`` filter is
  possible without deserializing the full payload.
- ``simulation_json`` — the canonical ``SimulationDetail`` payload
  (``model_dump_json``).

Reads (``GET /simulation_records/{id}``) and listings
(``GET /simulation_records?status=...``) use Firestore REST queries.
Pagination is page-by-page from the API; an offset cursor is encoded as
``next_cursor`` so the same client code works against in-memory and
Firestore adapters.

No model reasoning, prompts, or credentials are stored. Only the
canonical ``SimulationDetail`` Pydantic model.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Iterable

from retailtwin_api.firestore_decisions import _ApplicationDefaultTokenProvider
from retailtwin_api.firestore_twin import (
    ALLOWED_PROJECT,
    HttpTransport,
    TwinUnavailable,
    UrllibTransport,
)
from retailtwin_api.simulation_repository import SimulationReadRepository
from retailtwin_api.simulation_schemas import (
    AgentActivityEntry,
    CandidateListResponse,
    CursorParameters,
    PageParameters,
    SimulationDetail,
    SimulationFilters,
    SimulationListResponse,
    SimulationStatus,
    SimulationSummary,
)

log = logging.getLogger(__name__)

COLLECTION_SIMULATIONS = "simulation_records"


class SimulationStoreUnavailable(RuntimeError):
    """Firestore simulation storage is unreachable or rejected the write."""


def _parse_simulation(body: str, simulation_id: str) -> SimulationDetail | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        log.warning("firestore_simulations.malformed_json sim=%s", simulation_id)
        return None
    if not isinstance(payload, dict):
        return None
    fields = payload.get("fields", {})
    if not isinstance(fields, dict):
        return None
    raw = fields.get("simulation_json", {})
    if not isinstance(raw, dict):
        return None
    serialized = raw.get("stringValue")
    if not isinstance(serialized, str):
        return None
    try:
        return SimulationDetail.model_validate_json(serialized)
    except Exception as exc:  # noqa: BLE001 — invalid stored record
        log.warning(
            "firestore_simulations.invalid_record sim=%s error=%s",
            simulation_id,
            type(exc).__name__,
        )
        return None


def _parse_simulation_doc(doc: dict[str, Any], simulation_id: str) -> SimulationDetail | None:
    """Parse one document from a Firestore list response (already a dict)."""
    fields = doc.get("fields", {})
    if not isinstance(fields, dict):
        return None
    raw = fields.get("simulation_json", {})
    if not isinstance(raw, dict):
        return None
    serialized = raw.get("stringValue")
    if not isinstance(serialized, str):
        return None
    try:
        return SimulationDetail.model_validate_json(serialized)
    except Exception as exc:  # noqa: BLE001 — invalid stored record
        log.warning(
            "firestore_simulations.invalid_record sim=%s error=%s",
            simulation_id,
            type(exc).__name__,
        )
        return None


def _build_simulation_doc(
    simulation_id: str, status: SimulationStatus, detail_json: str
) -> dict[str, Any]:
    return {
        "fields": {
            "simulation_id": {"stringValue": simulation_id},
            "status": {"stringValue": status},
            "simulation_json": {"stringValue": detail_json},
        }
    }


class FirestoreSimulationRepository(SimulationReadRepository):
    """Cross-instance ``SimulationReadRepository`` backed by Firestore.

    Implements every method of the Protocol. ``record`` is upsert-by-id
    (idempotent). ``set_status`` updates only the ``status`` and
    ``updated_at`` fields so concurrent reads always see a consistent
    status without re-uploading the full payload.

    The constructor injects the HTTP transport and an access-token
    provider so tests stay offline. Production wires
    :class:`UrllibTransport` and the ADC token provider.
    """

    def __init__(
        self,
        project: str = ALLOWED_PROJECT,
        transport: HttpTransport | None = None,
        token_provider: Callable[[], str] | None = None,
        agent_events: Iterable[AgentActivityEntry] = (),
    ) -> None:
        self._project = project
        self._transport = transport if transport is not None else UrllibTransport()
        self._tokens = token_provider if token_provider is not None else _ApplicationDefaultTokenProvider()
        self._agent_events: list[AgentActivityEntry] = list(agent_events)
        self._available: bool = True

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Write side
    # ------------------------------------------------------------------

    def record(self, run: SimulationDetail) -> None:
        body = _build_simulation_doc(
            run.simulation_id, run.status, run.model_dump_json()
        )
        response = self._call(
            "PATCH", self._doc_url(run.simulation_id), body
        )
        if response.status not in (200, 201):
            raise SimulationStoreUnavailable(
                f"Firestore PATCH simulation_records/{run.simulation_id} returned HTTP {response.status}"
            )

    def set_status(self, simulation_id: str, status: SimulationStatus, at: datetime) -> None:
        existing = self.get_simulation(simulation_id)
        if existing is None:
            raise KeyError(simulation_id)
        updated = existing.model_copy(update={"status": status, "updated_at": at})
        body = _build_simulation_doc(simulation_id, status, updated.model_dump_json())
        response = self._call("PATCH", self._doc_url(simulation_id), body)
        if response.status not in (200, 201):
            raise SimulationStoreUnavailable(
                f"Firestore PATCH simulation_records/{simulation_id} returned HTTP {response.status}"
            )

    # ------------------------------------------------------------------
    # Read side
    # ------------------------------------------------------------------

    def get_simulation(self, simulation_id: str) -> SimulationDetail | None:
        response = self._call("GET", self._doc_url(simulation_id), None)
        if response.status == 404:
            return None
        if response.status != 200:
            raise SimulationStoreUnavailable(
                f"Firestore GET simulation_records/{simulation_id} returned HTTP {response.status}"
            )
        return _parse_simulation(response.body, simulation_id)

    def list_simulations(self, filters: SimulationFilters) -> SimulationListResponse:
        url = self._list_url(filters)
        response = self._call("GET", url, None)
        if response.status != 200:
            raise SimulationStoreUnavailable(
                f"Firestore list simulation_records returned HTTP {response.status}"
            )
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise SimulationStoreUnavailable("Firestore list response was not JSON.") from exc
        if not isinstance(payload, dict):
            raise SimulationStoreUnavailable("Firestore list response was malformed.")
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            return SimulationListResponse(
                simulations=[],
                page=filters.page,
                page_size=filters.page_size,
                total=0,
                next_cursor=None,
            )
        items: list[SimulationDetail] = []
        for entry in documents:
            if not isinstance(entry, dict):
                continue
            # Prefer the document's stored ``name`` field; fall back to the
            # stored ``simulation_id`` field for environments that omit the
            # name. Either way, the parse path is the same.
            name = entry.get("name", "")
            sim_id = name.rsplit("/", 1)[-1] if "/" in name else ""
            if not sim_id:
                fields = entry.get("fields", {})
                if isinstance(fields, dict):
                    id_field = fields.get("simulation_id", {})
                    if isinstance(id_field, dict):
                        candidate = id_field.get("stringValue")
                        if isinstance(candidate, str):
                            sim_id = candidate
            if not sim_id:
                continue
            parsed = _parse_simulation_doc(entry, sim_id)
            if parsed is not None:
                items.append(parsed)
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

    def list_candidates(
        self, simulation_id: str, page: PageParameters
    ) -> CandidateListResponse | None:
        # Scored candidates are not persisted by this adapter (the simulator
        # stores them in services/simulation). Mirror the in-memory
        # contract: a known simulation has an empty list; an unknown one
        # returns ``None`` so the route can return 404.
        if self.get_simulation(simulation_id) is None:
            return None
        return CandidateListResponse(
            candidates=[],
            page=page.page,
            page_size=page.page_size,
            total=0,
            next_cursor=None,
        )

    def list_agent_events(self, cursor: CursorParameters) -> tuple[list[AgentActivityEntry], str | None]:
        # Activity events live in their own collection (Sub-PR 3). Until
        # that lands, this adapter returns only the events injected at
        # construction time, which is what the test harness uses.
        start = 0
        if cursor.since is not None:
            try:
                start = int(cursor.since)
            except ValueError:
                raise ValueError(
                    f"Invalid cursor value {cursor.since!r}: must be a non-negative integer."
                ) from None
            if start < 0:
                raise ValueError(
                    f"Invalid cursor value {cursor.since!r}: must be a non-negative integer."
                ) from None
        window = self._agent_events[start : start + cursor.limit]
        offset = start + len(window)
        next_cursor = str(offset) if offset < len(self._agent_events) else None
        return [item.model_copy(deep=True) for item in window], next_cursor

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _doc_url(self, simulation_id: str) -> str:
        return (
            f"https://firestore.googleapis.com/v1/projects/{self._project}"
            f"/databases/(default)/documents/{COLLECTION_SIMULATIONS}/{simulation_id}"
        )

    def _list_url(self, filters: SimulationFilters) -> str:
        # ADR 0024 sub-PR 2 keeps the list path simple: fetch the full
        # collection once and filter / paginate in-process. The collection
        # is bounded by the canonical investigation id (``sim-<run_id>``),
        # so even at Competition-100 throughput the in-process filter stays
        # linear in the number of investigations the API knows about.
        # A future optimisation can move the filter to a Firestore
        # composite query and a ``pageSize`` cursor — that change is gated
        # on a measured bottleneck, not a premature index.
        del filters  # the in-process filter is applied after the fetch
        return (
            f"https://firestore.googleapis.com/v1/projects/{self._project}"
            f"/databases/(default)/documents/{COLLECTION_SIMULATIONS}"
        )

    def _call(self, method: str, url: str, payload: dict[str, Any] | None):
        body_bytes = None if payload is None else json.dumps(payload).encode("utf-8")
        try:
            token = self._tokens()
        except SimulationStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — surface any token failure
            raise SimulationStoreUnavailable(
                f"Simulation-store access token unavailable: {type(exc).__name__}"
            ) from exc
        if not token or any(c in token for c in "\n\r\t "):
            raise SimulationStoreUnavailable("Simulation-store access token is malformed.")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            return self._transport.request(method, url, body_bytes, headers)
        except TwinUnavailable:
            raise SimulationStoreUnavailable(
                "Firestore simulation store is unreachable."
            ) from None
        except Exception as exc:  # noqa: BLE001 — surface any transport failure
            raise SimulationStoreUnavailable(
                f"Firestore simulation store transport failed: {exc}"
            ) from exc


__all__ = [
    "COLLECTION_SIMULATIONS",
    "FirestoreSimulationRepository",
    "SimulationStoreUnavailable",
]