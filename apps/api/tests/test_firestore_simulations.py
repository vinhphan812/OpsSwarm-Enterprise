"""Tests for the Firestore-backed ``SimulationReadRepository`` (ADR 0024).

Uses the same hand-rolled ``FakeHttpTransport`` pattern as
``test_firestore_decisions.py``. The adapter's read path uses
``list_simulations`` + in-memory filtering; the write path is ``PATCH``
on a per-id document. ``set_status`` is an upsert that re-reads the doc,
re-serializes with the new status, and PATCHes again.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest

from retailtwin_api.contracts import MoveProduct
from retailtwin_api.firestore_simulations import (
    COLLECTION_SIMULATIONS,
    FirestoreSimulationRepository,
    SimulationStoreUnavailable,
)
from retailtwin_api.firestore_twin import HttpResponse
from retailtwin_api.simulation_schemas import (
    SimulationDetail,
    SimulationFilters,
    SimulationState,
    SimulationStatus,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class FakeHttpTransport:
    """Records calls and stores documents by simulation id."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        self.calls.append((method, url, payload))
        if method == "GET" and "/documents/" in url and "/simulation_records/" in url:
            for doc_id, doc in self._docs.items():
                if doc_id in url:
                    return HttpResponse(200, json.dumps(doc))
            return HttpResponse(
                404, json.dumps({"error": {"status": "NOT_FOUND"}})
            )
        if method == "GET" and (
            url.endswith(COLLECTION_SIMULATIONS)
            or url.endswith(f"{COLLECTION_SIMULATIONS}?")
            or f"/{COLLECTION_SIMULATIONS}?" in url
        ):
            documents = list(self._docs.values())
            return HttpResponse(
                200, json.dumps({"documents": documents})
            )
        if method == "PATCH" and "/documents/" in url:
            if payload is None:
                return HttpResponse(
                    400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}})
                )
            decoded = json.loads(payload.decode())
            doc_id = url.rsplit("/", 1)[-1]
            existing = self._docs.get(doc_id, {})
            merged = {**existing, **decoded}
            self._docs[doc_id] = merged
            return HttpResponse(200, json.dumps(merged))
        return HttpResponse(200, json.dumps({}))


class _FakeToken:
    def __call__(self) -> str:
        return "fake-token"


def _detail(simulation_id: str = "sim-test", status: SimulationStatus = "pending") -> SimulationDetail:
    """Build a small SimulationDetail for round-trip testing."""
    return SimulationDetail(
        simulation_id=simulation_id,
        store_id="store-001",
        base_context_version="store-001:v1",
        status=status,
        created_at=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
        provenance="test",
        actions=[MoveProduct(sku="P017", from_slot="A02-S03", to_slot="B02-S01")],
        state=SimulationState(
            store={
                "store_id": "store-001",
                "context_version": "store-001:v1+sim:test",
                "version": "v1",
                "products": [],
            },  # type: ignore[arg-type]
            context_version="store-001:v1+sim:test",
        ),
        correlation_id="corr-test",
        agent_id="agent-test",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFirestoreSimulationRepositoryRoundTrip:
    def test_record_then_get_round_trips_detail(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        detail = _detail("sim-weekend-surge-1")

        repo.record(detail)
        loaded = repo.get_simulation("sim-weekend-surge-1")

        assert loaded is not None
        assert loaded.simulation_id == detail.simulation_id
        assert loaded.status == detail.status
        assert loaded.provenance == detail.provenance
        # PATCH on canonical URL.
        assert any(
            f"simulation_records/sim-weekend-surge-1" in url for _, url, _ in transport.calls
        )

    def test_record_serializes_full_detail_as_string_value(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        detail = _detail()

        repo.record(detail)
        method, url, payload = transport.calls[0]
        assert method == "PATCH"
        assert url.endswith("/simulation_records/sim-test")
        decoded = json.loads(payload.decode())
        assert decoded["fields"]["simulation_id"] == {"stringValue": "sim-test"}
        assert decoded["fields"]["status"] == {"stringValue": "pending"}
        json_payload = decoded["fields"]["simulation_json"]["stringValue"]
        re_decoded = SimulationDetail.model_validate_json(json_payload)
        assert re_decoded == detail

    def test_record_uses_correct_collection_path(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )

        repo.record(_detail("sim-path"))

        method, url, _ = transport.calls[0]
        assert f"/{COLLECTION_SIMULATIONS}/sim-path" in url
        assert "retailtwin-ai-511002" in url


class TestFirestoreSimulationRepositoryMissing:
    def test_get_returns_none_on_404(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        assert repo.get_simulation("sim-missing") is None


class TestFirestoreSimulationRepositorySetStatus:
    def test_set_status_updates_existing_record(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        detail = _detail("sim-status", status="pending")
        repo.record(detail)

        new_time = datetime(2026, 10, 16, 13, 0, 0, tzinfo=timezone.utc)
        repo.set_status("sim-status", "committed", new_time)

        loaded = repo.get_simulation("sim-status")
        assert loaded is not None
        assert loaded.status == "committed"
        assert loaded.updated_at == new_time

    def test_set_status_raises_keyerror_on_missing(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        with pytest.raises(KeyError):
            repo.set_status(
                "sim-missing", "committed", datetime.now(timezone.utc)
            )


class TestFirestoreSimulationRepositoryListSimulations:
    def test_list_simulations_returns_persisted_records(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        repo.record(_detail("sim-a"))
        repo.record(_detail("sim-b", status="committed"))
        transport.calls.clear()  # ignore the writes

        result = repo.list_simulations(SimulationFilters(page=1, page_size=10))

        assert result.total == 2
        ids = sorted(item.simulation_id for item in result.simulations)
        assert ids == ["sim-a", "sim-b"]

    def test_list_simulations_filters_by_status(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        repo.record(_detail("sim-open", status="pending"))
        repo.record(_detail("sim-done", status="committed"))
        transport.calls.clear()

        result = repo.list_simulations(SimulationFilters(status="open", page=1, page_size=10))

        ids = [item.simulation_id for item in result.simulations]
        assert ids == ["sim-open"]


class TestFirestoreSimulationRepositoryFailureClosed:
    def test_record_raises_on_unexpected_status(self) -> None:
        class _FailTransport(FakeHttpTransport):
            def request(self, method, url, payload, headers):
                if method == "PATCH":
                    return HttpResponse(
                        500, json.dumps({"error": {"status": "INTERNAL"}})
                    )
                return super().request(method, url, payload, headers)

        repo = FirestoreSimulationRepository(
            transport=_FailTransport(), token_provider=_FakeToken()
        )
        with pytest.raises(SimulationStoreUnavailable):
            repo.record(_detail("sim-fail"))

    def test_record_raises_on_token_failure(self) -> None:
        def broken_token() -> str:
            raise RuntimeError("ADC missing")

        repo = FirestoreSimulationRepository(
            transport=FakeHttpTransport(), token_provider=broken_token
        )
        with pytest.raises(SimulationStoreUnavailable):
            repo.record(_detail("sim-no-token"))


class TestFirestoreSimulationRepositoryListCandidates:
    def test_list_candidates_returns_none_for_missing_simulation(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        from retailtwin_api.simulation_schemas import PageParameters

        assert repo.list_candidates("sim-missing", PageParameters(page=1, page_size=10)) is None

    def test_list_candidates_returns_empty_for_known_simulation(self) -> None:
        transport = FakeHttpTransport()
        repo = FirestoreSimulationRepository(
            transport=transport, token_provider=_FakeToken()
        )
        repo.record(_detail("sim-known"))
        from retailtwin_api.simulation_schemas import PageParameters

        result = repo.list_candidates("sim-known", PageParameters(page=1, page_size=10))
        assert result is not None
        assert result.candidates == []
        assert result.total == 0


class TestFirestoreSimulationRepositoryAvailable:
    def test_available_is_true_when_constructed(self) -> None:
        repo = FirestoreSimulationRepository(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        assert repo.available is True