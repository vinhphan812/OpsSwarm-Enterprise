"""Tests for the Firestore-backed ``MemoryActivationLedger`` (ADR 0024).

Same hand-rolled ``FakeHttpTransport`` pattern as the other Firestore
adapter tests. Covers reserve (owner/duplicate/conflict), commit,
abort, get, and the typed failure on transport errors.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import pytest

from retailtwin_api.agents.observer.consumer import (
    Activation,
    MemoryActivationLedger,
    ObservationError,
)
from retailtwin_api.firestore_activation_ledger import (
    COLLECTION_ACTIVATIONS,
    ActivationLedgerUnavailable,
    FirestoreActivationLedger,
)
from retailtwin_api.firestore_twin import HttpResponse
from retailtwin_api.schemas import StoreEvent


class FakeHttpTransport:
    """Records calls and stores documents by event id.

    Mirrors Firestore's REST contract for the activation ledger: GET,
    DELETE, and the atomic ``:commit`` endpoint used by the durable
    pipeline. The fake evaluates ``currentDocument.exists`` /
    ``currentDocument.updateTime`` preconditions on the server side.

    Thread-safe: two ``FirestoreActivationLedger`` clients can share one
    instance and exercise the ``:commit`` atomically so the concurrency
    tests can drive a real cross-instance race.
    """

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._versions: dict[str, int] = {}
        self._calls_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.calls: list[tuple[str, str, bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        with self._calls_lock:
            self.calls.append((method, url, payload))
        if method == "GET" and "/documents/" in url:
            with self._state_lock:
                for event_id, doc in self._docs.items():
                    if event_id in url:
                        return HttpResponse(
                            200,
                            json.dumps({**doc, "updateTime": f"v{self._versions[event_id]}"}),
                        )
            return HttpResponse(
                404, json.dumps({"error": {"status": "NOT_FOUND"}})
            )
        if method == "DELETE" and "/documents/" in url:
            with self._state_lock:
                for event_id in list(self._docs.keys()):
                    if event_id in url:
                        del self._docs[event_id]
                        self._versions.pop(event_id, None)
                        return HttpResponse(200, json.dumps({"writeResults": [{"delete": {}}]}))
            return HttpResponse(
                404, json.dumps({"error": {"status": "NOT_FOUND"}})
            )
        if method == "POST" and url.endswith(":commit"):
            with self._state_lock:
                return self._commit(payload)
        if method == "PATCH" and "/documents/" in url:
            if payload is None:
                return HttpResponse(
                    400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}})
                )
            decoded = json.loads(payload.decode())
            event_id = url.rsplit("/", 1)[-1]
            with self._state_lock:
                existing = self._docs.get(event_id, {})
                merged = {**existing, **decoded}
                self._docs[event_id] = merged
                self._versions[event_id] = self._versions.get(event_id, 0) + 1
            return HttpResponse(200, json.dumps(merged))
        return HttpResponse(200, json.dumps({}))

    def _commit(self, payload: bytes | None) -> HttpResponse:
        body = json.loads((payload or b"{}").decode())
        writes = body.get("writes") or []
        if not isinstance(writes, list) or len(writes) != 1:
            return HttpResponse(
                400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}})
            )
        write = writes[0]
        if "update" in write:
            update = write["update"]
            doc_name = update.get("name", "") if isinstance(update, dict) else ""
            event_id = doc_name.rsplit("/", 1)[-1]
            existing = self._docs.get(event_id)
            precondition = write.get("currentDocument", {})
            if isinstance(precondition, dict):
                if "exists" in precondition:
                    if precondition.get("exists") is False and existing is not None:
                        return HttpResponse(
                            409,
                            json.dumps({
                                "error": {
                                    "status": "ALREADY_EXISTS",
                                    "message": "Document already exists",
                                }
                            }),
                        )
                    if precondition.get("exists") is True and existing is None:
                        return HttpResponse(
                            409,
                            json.dumps({
                                "error": {
                                    "status": "NOT_FOUND",
                                    "message": "Document does not exist",
                                }
                            }),
                        )
                if "updateTime" in precondition:
                    expected = precondition.get("updateTime")
                    if existing is None:
                        return HttpResponse(
                            409,
                            json.dumps({
                                "error": {
                                    "status": "FAILED_PRECONDITION",
                                    "message": f"Document updateTime mismatch (expected {expected})",
                                }
                            }),
                        )
                    current_version = self._versions.get(event_id, 0)
                    actual = f"v{current_version}"
                    if expected != actual:
                        return HttpResponse(
                            409,
                            json.dumps({
                                "error": {
                                    "status": "FAILED_PRECONDITION",
                                    "message": (
                                        f"Document updateTime mismatch "
                                        f"(expected {expected}, actual {actual})"
                                    ),
                                }
                            }),
                        )
            # Apply the write.
            self._docs[event_id] = update
            self._versions[event_id] = self._versions.get(event_id, 0) + 1
            return HttpResponse(
                200,
                json.dumps({
                    "writeResults": [{
                        "updateTime": f"v{self._versions[event_id]}",
                    }]
                }),
            )
        if "delete" in write:
            doc_name = write.get("delete", "") if isinstance(write, dict) else ""
            event_id = doc_name.rsplit("/", 1)[-1] if isinstance(doc_name, str) else ""
            existing = self._docs.get(event_id)
            precondition = write.get("currentDocument", {})
            if isinstance(precondition, dict) and "updateTime" in precondition:
                expected = precondition.get("updateTime")
                current_version = self._versions.get(event_id, 0)
                actual = f"v{current_version}"
                if existing is None or expected != actual:
                    return HttpResponse(
                        409,
                        json.dumps({
                            "error": {
                                "status": "FAILED_PRECONDITION",
                                "message": (
                                    f"Document updateTime mismatch "
                                    f"(expected {expected}, actual {actual})"
                                ),
                            }
                        }),
                    )
            # Apply the delete.
            self._docs.pop(event_id, None)
            self._versions.pop(event_id, None)
            return HttpResponse(
                200,
                json.dumps({"writeResults": [{"delete": {}}]}),
            )
        return HttpResponse(
            400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}})
        )


class _FakeToken:
    def __call__(self) -> str:
        return "fake-token"


def _event(event_id: str = "evt-1") -> StoreEvent:
    return StoreEvent(
        event_id=event_id,
        correlation_id=f"corr-{event_id}",
        event_type="sale.completed",
        store_id="store-001",
        sku="P001",
        quantity=1,
        occurred_at=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
        source="synthetic-pos",
    )


class TestFirestoreActivationLedgerReserve:
    def test_first_reserve_is_owner(self) -> None:
        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        reservation = ledger.reserve(_event("evt-1"))
        assert reservation.kind == "owner"
        assert reservation.investigation_id == "inv-evt-1"

    def test_second_reserve_with_same_event_is_duplicate(self) -> None:
        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        event = _event("evt-1")
        first = ledger.reserve(event)
        assert first.kind == "owner"

        ledger.commit("evt-1")  # advance status to "started"
        second = ledger.reserve(event)
        assert second.kind == "duplicate"

    def test_reserve_with_different_payload_is_conflict(self) -> None:
        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-1"))

        different = StoreEvent(
            event_id="evt-1",
            correlation_id="corr-evt-1",
            event_type="sale.completed",
            store_id="store-002",  # different store
            sku="P001",
            quantity=1,
            occurred_at=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
            source="synthetic-pos",
        )
        reservation = ledger.reserve(different)
        assert reservation.kind == "conflict"


class TestFirestoreActivationLedgerCommit:
    def test_commit_advances_status_to_started(self) -> None:
        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-1"))
        ledger.commit("evt-1")
        activated = ledger.get("evt-1")
        assert activated is not None
        assert activated.status == "started"

    def test_commit_raises_observation_error_when_no_reservation(self) -> None:
        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        with pytest.raises(ObservationError):
            ledger.commit("evt-missing")


class TestFirestoreActivationLedgerAbort:
    def test_abort_removes_reservation(self) -> None:
        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-1"))
        ledger.abort("evt-1")
        assert ledger.get("evt-1") is None

    def test_abort_on_missing_event_id_is_noop(self) -> None:
        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        # Should not raise even though the doc is absent.
        ledger.abort("evt-missing")


class TestFirestoreActivationLedgerFailureClosed:
    def test_reserve_raises_on_token_failure(self) -> None:
        def broken_token() -> str:
            raise RuntimeError("ADC missing")

        ledger = FirestoreActivationLedger(
            transport=FakeHttpTransport(), token_provider=broken_token
        )
        with pytest.raises(ActivationLedgerUnavailable):
            ledger.reserve(_event("evt-1"))

    def test_uses_correct_collection_path(self) -> None:
        transport = FakeHttpTransport()
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-path"))
        method, url, _ = transport.calls[0]
        assert f"/{COLLECTION_ACTIVATIONS}/evt-path" in url
        assert "retailtwin-ai-511002" in url


class TestFirestoreActivationLedgerAtomicReservation:
    """Lock down the cross-instance race condition reported in the
    CHANGES_REQUESTED review of PR #231. ``reserve`` must not allow two
    instances to both become owner for the same ``event_id``.
    """

    def test_reserve_uses_atomic_create_with_exists_false(self) -> None:
        transport = FakeHttpTransport()
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-atomic"))
        # The first call must use the POST :commit endpoint with
        # currentDocument.exists=false — not a bare PATCH.
        write_calls = [
            (method, url, payload)
            for method, url, payload in transport.calls
            if method == "POST" and url.endswith(":commit")
        ]
        assert len(write_calls) == 1, write_calls
        body = json.loads(write_calls[0][2].decode())  # type: ignore[arg-type]
        writes = body.get("writes")
        assert isinstance(writes, list) and len(writes) == 1
        write = writes[0]
        assert write.get("currentDocument") == {"exists": False}
        assert "/activation_records/evt-atomic" in write.get("update", {}).get("name", "")

    def test_concurrent_create_loses_precondition_and_reclassifies(self) -> None:
        """When the create precondition is lost, ``reserve`` must NOT
        write the document a second time. It re-reads, finds the
        existing record, and classifies as ``duplicate``.
        """
        transport = FakeHttpTransport()
        # Pre-seed an existing record so the create precondition fails.
        transport._docs["evt-2"] = {
            "fields": {
                "event_id": {"stringValue": "evt-2"},
                "investigation_id": {"stringValue": "inv-evt-2"},
                "status": {"stringValue": "started"},
                "event_json": {"stringValue": _event("evt-2").model_dump_json()},
            }
        }
        transport._versions["evt-2"] = 1
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        reservation = ledger.reserve(_event("evt-2"))
        assert reservation.kind == "duplicate"
        # The pre-seeded investigation_id is preserved; the second
        # reserve did not overwrite it.
        assert reservation.investigation_id == "inv-evt-2"

    def test_concurrent_create_with_different_payload_is_conflict(self) -> None:
        transport = FakeHttpTransport()
        transport._docs["evt-3"] = {
            "fields": {
                "event_id": {"stringValue": "evt-3"},
                "investigation_id": {"stringValue": "inv-evt-3"},
                "status": {"stringValue": "pending"},
                "event_json": {"stringValue": _event("evt-3").model_dump_json()},
            }
        }
        transport._versions["evt-3"] = 1
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        different = StoreEvent(
            event_id="evt-3",
            correlation_id="corr-evt-3",
            event_type="sale.completed",
            store_id="store-002",
            sku="P001",
            quantity=1,
            occurred_at=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
            source="synthetic-pos",
        )
        reservation = ledger.reserve(different)
        assert reservation.kind == "conflict"

    def test_commit_uses_update_time_precondition(self) -> None:
        transport = FakeHttpTransport()
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-4"))
        ledger.commit("evt-4")
        commit_calls = [
            (method, url, payload)
            for method, url, payload in transport.calls
            if method == "POST" and url.endswith(":commit")
        ]
        assert len(commit_calls) == 2, commit_calls
        body = json.loads(commit_calls[1][2].decode())  # type: ignore[arg-type]
        write = body["writes"][0]
        assert "updateTime" in write.get("currentDocument", {})
        assert write["currentDocument"]["updateTime"] == "v1"


class TestFirestoreActivationOwnerTokenExclusivity:
    """Fenced ``owner_token`` reservations (P0 idempotency blocker).

    The previous atomic create commit (``2b81f5a``, re-anchored to
    ``37f4d2d``) used ``currentDocument.exists=false`` so a GET→PATCH
    race could not double-create. That alone, however, did NOT
    distinguish the original creator from a retry handled by a second
    Cloud Run instance: both would observe a ``pending`` record and the
    loser still classified as ``owner``. Each ``reserve`` now mints a
    unique ``owner_token``; the loser's re-read sees the foreign token
    on a ``pending`` record and classifies as ``in_flight`` so the
    consumer acks the Pub/Sub message without starting a second
    investigation.
    """

    def test_reserve_stores_owner_token_in_initial_create(self) -> None:
        transport = FakeHttpTransport()
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        reservation = ledger.reserve(_event("evt-tok"))
        assert reservation.kind == "owner"
        # The first :commit body must carry owner_token.
        commit_calls = [
            (method, url, payload)
            for method, url, payload in transport.calls
            if method == "POST" and url.endswith(":commit")
        ]
        assert len(commit_calls) == 1, commit_calls
        body = json.loads(commit_calls[0][2].decode())  # type: ignore[arg-type]
        write = body["writes"][0]
        fields = write["update"]["fields"]
        assert "owner_token" in fields
        assert isinstance(fields["owner_token"], dict)
        token = fields["owner_token"].get("stringValue")
        assert isinstance(token, str) and len(token) > 0

    def test_concurrent_reserve_chooses_one_owner_and_one_in_flight(self) -> None:
        """Two ``FirestoreActivationLedger`` clients (== two Cloud Run
        instances) share one ``FakeHttpTransport`` and call
        ``reserve`` simultaneously. Exactly one returns ``owner``; the
        other returns ``in_flight`` (or, if a peer already advanced the
        state to ``started``, ``duplicate``). The losing reservation
        must NOT commit — so the message gets acked without spawning
        a duplicate investigation.
        """
        transport = FakeHttpTransport()
        client_a = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        client_b = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )

        def _reserve(client: Any) -> Any:
            return client.reserve(_event("evt-race"))

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(_reserve, client_a)
            future_b = executor.submit(_reserve, client_b)
            reservation_a = future_a.result(timeout=10)
            reservation_b = future_b.result(timeout=10)

        kinds = sorted([reservation_a.kind, reservation_b.kind])
        # Exactly one owner, and the loser must NOT be owner.
        assert kinds.count("owner") == 1, (reservation_a.kind, reservation_b.kind)
        loser_kinds = [k for k in kinds if k != "owner"]
        assert loser_kinds and set(loser_kinds) <= {"in_flight", "duplicate"}, kinds

        # The winning :commit must include currentDocument.exists=false.
        exists_false_calls = []
        for method, url, payload in transport.calls:
            if method != "POST" or not url.endswith(":commit"):
                continue
            body = json.loads(payload.decode())  # type: ignore[union-attr]
            writes = body.get("writes") or []
            if not writes:
                continue
            current = writes[0].get("currentDocument", {})
            if isinstance(current, dict) and current.get("exists") is False:
                exists_false_calls.append(body)
        assert len(exists_false_calls) == 1, transport.calls

        # The losing client must NOT have issued a write that created
        # a second document. Exactly one document id is present in the
        # fake transport.
        assert set(transport._docs.keys()) == {"evt-race"}, transport._docs

    def test_reserve_re_read_sees_foreign_owner_token_classifies_in_flight(
        self,
    ) -> None:
        """Simulate the second-arriving client with the existing record
        pre-seeded and a known foreign ``owner_token``. The reservation
        kind must be ``in_flight`` so the consumer does not start a
        duplicate investigation.
        """
        transport = FakeHttpTransport()
        transport._docs["evt-fence"] = {
            "fields": {
                "event_id": {"stringValue": "evt-fence"},
                "investigation_id": {"stringValue": "inv-evt-fence"},
                "status": {"stringValue": "pending"},
                "event_json": {"stringValue": _event("evt-fence").model_dump_json()},
                "owner_token": {"stringValue": "foreign-token-xyz"},
            }
        }
        transport._versions["evt-fence"] = 1
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        reservation = ledger.reserve(_event("evt-fence"))
        assert reservation.kind == "in_flight"
        assert reservation.investigation_id == "inv-evt-fence"

    def test_reserve_re_read_on_started_record_classifies_duplicate(self) -> None:
        """Even when the foreign ``owner_token`` differs, a ``started``
        record means another instance has committed — the second client
        must classify as ``duplicate``, NOT ``in_flight``.
        """
        transport = FakeHttpTransport()
        transport._docs["evt-dup"] = {
            "fields": {
                "event_id": {"stringValue": "evt-dup"},
                "investigation_id": {"stringValue": "inv-evt-dup"},
                "status": {"stringValue": "started"},
                "event_json": {"stringValue": _event("evt-dup").model_dump_json()},
                "owner_token": {"stringValue": "foreign-token-abc"},
            }
        }
        transport._versions["evt-dup"] = 1
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        reservation = ledger.reserve(_event("evt-dup"))
        assert reservation.kind == "duplicate"
        # The losing client must NOT have committed any new write.
        commit_calls = [
            payload
            for method, url, payload in transport.calls
            if method == "POST" and url.endswith(":commit")
        ]
        assert commit_calls == []


class TestFirestoreActivationFencedAbort:
    """Conditional ``abort`` fenced by the reservation we observed.

    The previous implementation called a primitive ``DELETE`` on the
    document URL, which is racy: a later owner's ``commit`` may have
    already raised the document's ``updateTime``, so a blind DELETE
    could remove that owner's reservation. ``abort`` now issues a
    ``:commit`` with ``currentDocument.updateTime=<reserved-updateTime>``
    so a precondition loss becomes a quiet no-op (``abort_loser``).
    """

    def test_abort_uses_commit_with_update_time_precondition(self) -> None:
        transport = FakeHttpTransport()
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-ab1"))
        # Reset recorded calls so the assertions target only abort.
        transport.calls.clear()
        ledger.abort("evt-ab1")
        delete_calls = [
            (method, url, payload)
            for method, url, payload in transport.calls
            if method == "POST" and url.endswith(":commit")
        ]
        assert len(delete_calls) == 1, delete_calls
        body = json.loads(delete_calls[0][2].decode())  # type: ignore[arg-type]
        write = body["writes"][0]
        assert "delete" in write, write
        precondition = write.get("currentDocument", {})
        assert "updateTime" in precondition
        assert precondition["updateTime"] == "v1"

    def test_abort_is_noop_when_precondition_lost(self) -> None:
        """A second instance has progressed the reservation
        (e.g. ``commit`` advanced ``updateTime`` from v1 → v2). Our
        ``abort`` carries the stale v1 expectation, the precondition
        fails, and ``abort`` becomes a no-op — it must NOT issue a raw
        DELETE on the document.
        """
        transport = FakeHttpTransport()
        ledger = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        ledger.reserve(_event("evt-ab2"))
        # Simulate a peer instance committing: bump the version.
        with transport._state_lock:
            transport._versions["evt-ab2"] = 2
        transport.calls.clear()
        ledger.abort("evt-ab2")
        # The peer-committed record must still be retrievable; we did
        # not delete it.
        doc_after = transport._docs.get("evt-ab2")
        assert doc_after is not None, transport._docs
        # And there must be no raw DELETE on the document URL.
        raw_deletes = [
            (method, url)
            for method, url, _ in transport.calls
            if method == "DELETE"
        ]
        assert raw_deletes == [], raw_deletes
        # The :commit precondition failure is recorded as a single call.
        commit_calls = [
            payload
            for method, url, payload in transport.calls
            if method == "POST" and url.endswith(":commit")
        ]
        assert len(commit_calls) == 1, transport.calls

    def test_peer_commit_then_abort_does_not_delete_reservation(self) -> None:
        """End-to-end race: client A reserves, commits, then a stale
        abort from an earlier reservation attempt arrives. The
        reservation must survive — the post-commit record is preserved
        so a downstream caller still sees the investigation.
        """
        transport = FakeHttpTransport()
        client_a = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )
        client_b = FirestoreActivationLedger(
            transport=transport, token_provider=_FakeToken()
        )

        def _client_b_first_read() -> Any:
            # client_b observes the doc but does not yet call abort;
            # it stores the v1 snapshot it read at startup.
            existing = client_b._read_with_full("evt-ab3")
            assert existing is not None
            return existing

        # client_a wins the reservation, then commits.
        reservation = client_a.reserve(_event("evt-ab3"))
        assert reservation.kind == "owner"
        # client_b observed the doc at v1 BEFORE the commit.
        b_observation = _client_b_first_read()
        assert b_observation.update_time == "v1"
        # client_a commits.
        client_a.commit("evt-ab3")
        # Now client_b tries to abort using the stale v1 fence. The
        # precondition fails; abort is a no-op.
        with client_b._lock:
            client_b._reservations["evt-ab3"] = b_observation
        client_b.abort("evt-ab3")
        # client_a's commit must survive — the post-commit doc is
        # still retrievable from the fake transport.
        surviving = transport._docs.get("evt-ab3")
        assert surviving is not None
        committed = client_a.get("evt-ab3")
        assert committed is not None
        assert committed.status == "started"
