"""Tests for the Firestore-backed ``DecisionSource`` (ADR 0024).

These tests use a hand-rolled ``FakeHttpTransport`` rather than
``FakeFirestoreTransport`` so the contract under test is the small slice of
the Firestore REST API that ``FirestoreDecisionSource`` actually uses
(``PATCH`` for write, ``GET`` for read, ``404`` for missing). The production
path goes through ``UrllibTransport`` and Application Default Credentials,
both injected so no real network call is required.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel

from retailtwin_api.contracts import Decision, ExpectedImpact, MoveProduct
from retailtwin_api.firestore_decisions import (
    COLLECTION_DECISIONS,
    DecisionStoreUnavailable,
    FirestoreDecisionSource,
)
from retailtwin_api.firestore_twin import HttpResponse


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class FakeHttpTransport:
    """Records every call and returns canned responses.

    The handler is a callable: ``handler(method, url, payload) -> HttpResponse``.
    A missing handler returns ``HTTP 200`` and an empty body so callers that
    only inspect the URL still record the call.
    """

    def __init__(
        self,
        handler: Any = None,
        *,
        initial_docs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._handler = handler
        self._docs: dict[str, dict[str, Any]] = dict(initial_docs or {})
        self.calls: list[tuple[str, str, bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        self.calls.append((method, url, payload))
        if self._handler is not None:
            response = self._handler(method, url, payload, self._docs)
            if response is not None:
                return response
        if method == "GET" and "/documents/" in url:
            for key, doc in self._docs.items():
                if key in url:
                    return HttpResponse(200, json.dumps(doc))
            return HttpResponse(
                404, json.dumps({"error": {"status": "NOT_FOUND"}})
            )
        if method == "PATCH" and "/documents/" in url:
            if payload is None:
                return HttpResponse(400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}}))
            try:
                decoded = json.loads(payload.decode())
            except json.JSONDecodeError:
                return HttpResponse(
                    400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}})
                )
            for doc_key in self._docs:
                if doc_key in url:
                    self._docs[doc_key] = decoded
                    return HttpResponse(200, json.dumps(decoded))
            self._docs[url.rsplit("/", 1)[-1]] = decoded
            return HttpResponse(200, json.dumps(decoded))
        return HttpResponse(200, json.dumps({}))


class _FakeToken:
    def __call__(self) -> str:
        return "fake-token"


def _decision(simulation_id: str = "sim-test") -> Decision:
    """Build a small valid Decision for round-trip testing."""
    return Decision(
        decision_id="dec-test-001",
        agent_id="agent-test",
        context_version="store-001:v1",
        context_timestamp=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc),
        evidence=[],
        proposed_actions=[MoveProduct(sku="P017", from_slot="A02-S03", to_slot="B02-S01")],
        simulation_id=simulation_id,
        expected_impact=ExpectedImpact(kpi_score=0.12, description="test candidate"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFirestoreDecisionSourceRoundTrip:
    def test_put_then_get_round_trips_decision(self) -> None:
        transport = FakeHttpTransport()
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        decision = _decision("sim-weekend-surge-1")

        source.put("sim-weekend-surge-1", decision)
        loaded = source.get_for_simulation("sim-weekend-surge-1")

        assert loaded == decision
        # Both calls hit the same canonical URL.
        assert all(
            f"decision_records/sim-weekend-surge-1" in url for _, url, _ in transport.calls
        )

    def test_put_serializes_decision_as_firestore_string_value(self) -> None:
        transport = FakeHttpTransport()
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        decision = _decision()

        source.put("sim-x", decision)
        # put() issues GET (CAS read) then PATCH (write).
        assert len(transport.calls) == 2
        get_call, patch_call = transport.calls
        assert get_call[0] == "GET"
        assert patch_call[0] == "PATCH"
        assert patch_call[1].endswith("/decision_records/sim-x")
        assert patch_call[2] is not None
        decoded = json.loads(patch_call[2].decode())
        assert decoded["fields"]["simulation_id"] == {"stringValue": "sim-x"}
        decision_json = decoded["fields"]["decision_json"]["stringValue"]
        # Round-trip through model_validate_json to confirm canonical form.
        re_decoded = Decision.model_validate_json(decision_json)
        assert re_decoded == decision
        # CAS hash is also stored.
        assert "decision_hash" in decoded["fields"]

    def test_put_sends_bearer_token(self) -> None:
        captured_headers: list[Mapping[str, str]] = []

        def handler(method, url, payload, _docs):
            return None  # fall through to default

        class HeaderCapture(FakeHttpTransport):
            def request(self, method, url, payload, headers):
                captured_headers.append(dict(headers))
                return super().request(method, url, payload, headers)

        source = FirestoreDecisionSource(
            transport=HeaderCapture(handler), token_provider=_FakeToken()
        )
        source.put("sim-auth", _decision())
        assert any(
            h.get("Authorization") == "Bearer fake-token" for h in captured_headers
        )


class TestFirestoreDecisionSourceMissing:
    def test_get_returns_none_on_404(self) -> None:
        transport = FakeHttpTransport()  # empty; no initial docs
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )

        assert source.get_for_simulation("sim-missing") is None

    def test_get_returns_none_on_malformed_json(self) -> None:
        def handler(method, url, payload, _docs):
            if method == "GET" and "sim-broken" in url:
                return HttpResponse(200, "not-json")
            return None

        transport = FakeHttpTransport(handler=handler)
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        assert source.get_for_simulation("sim-broken") is None

    def test_get_returns_none_on_missing_decision_json_field(self) -> None:
        def handler(method, url, payload, _docs):
            if method == "GET" and "sim-nofield" in url:
                return HttpResponse(
                    200, json.dumps({"fields": {"other": {"stringValue": "x"}}})
                )
            return None

        transport = FakeHttpTransport(handler=handler)
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        assert source.get_for_simulation("sim-nofield") is None


class TestFirestoreDecisionSourceFailureClosed:
    def test_put_raises_on_unexpected_status(self) -> None:
        def handler(method, url, payload, _docs):
            if method == "PATCH":
                return HttpResponse(
                    500, json.dumps({"error": {"status": "INTERNAL"}})
                )
            return None

        transport = FakeHttpTransport(handler=handler)
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )

        with pytest.raises(DecisionStoreUnavailable):
            source.put("sim-fail", _decision())

    def test_get_raises_on_unexpected_status(self) -> None:
        def handler(method, url, payload, _docs):
            if method == "GET":
                return HttpResponse(
                    503, json.dumps({"error": {"status": "UNAVAILABLE"}})
                )
            return None

        transport = FakeHttpTransport(handler=handler)
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        with pytest.raises(DecisionStoreUnavailable):
            source.get_for_simulation("sim-503")

    def test_put_raises_on_token_failure(self) -> None:
        def broken_token() -> str:
            raise RuntimeError("ADC missing")

        source = FirestoreDecisionSource(
            transport=FakeHttpTransport(), token_provider=broken_token
        )
        with pytest.raises(DecisionStoreUnavailable):
            source.put("sim-no-token", _decision())

    def test_put_raises_on_invalid_token_shape(self) -> None:
        class _WeirdToken:
            def __call__(self) -> str:
                return "bad\ntoken"

        source = FirestoreDecisionSource(
            transport=FakeHttpTransport(), token_provider=_WeirdToken()
        )
        with pytest.raises(DecisionStoreUnavailable):
            source.put("sim-bad-token", _decision())


class TestFirestoreDecisionSourceIdempotent:
    def test_put_same_payload_is_idempotent(self) -> None:
        """Same payload at the same simulation_id: second write succeeds (idempotent retry)."""
        transport = FakeHttpTransport()
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        # Pre-seed an existing document with the same payload hash.
        first = _decision("sim-idem")
        transport._docs["sim-idem"] = {
            "fields": {
                "simulation_id": {"stringValue": "sim-idem"},
                "decision_json": {"stringValue": first.model_dump_json()},
                "decision_hash": {
                    "stringValue": FirestoreDecisionSource._decision_hash(first)
                },
            }
        }
        # Same payload: should not raise.
        source.put("sim-idem", first)

    def test_put_different_payload_raises_conflict(self) -> None:
        """Different Decision payload at same simulation_id raises DecisionConflict."""
        from retailtwin_api.firestore_decisions import DecisionConflict

        transport = FakeHttpTransport()
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        first = _decision("sim-conflict")
        transport._docs["sim-conflict"] = {
            "fields": {
                "simulation_id": {"stringValue": "sim-conflict"},
                "decision_json": {"stringValue": first.model_dump_json()},
                "decision_hash": {
                    "stringValue": FirestoreDecisionSource._decision_hash(first)
                },
            }
        }
        # Second decision with the same sim-id but a different payload.
        second = _decision("sim-conflict")
        object.__setattr__(second, "decision_id", "dec-conflicting")
        with pytest.raises(DecisionConflict) as exc_info:
            source.put("sim-conflict", second)
        assert "different payload" in str(exc_info.value)
        assert "hash mismatch" in str(exc_info.value)

    def test_put_raises_on_get_failure(self) -> None:
        """A non-404, non-200 GET response raises DecisionStoreUnavailable."""
        def handler(method, url, payload, _docs):
            if method == "GET" and "sim-500" in url:
                return HttpResponse(
                    503, json.dumps({"error": {"status": "UNAVAILABLE"}})
                )
            return None

        transport = FakeHttpTransport(handler=handler)
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        with pytest.raises(DecisionStoreUnavailable):
            source.put("sim-500", _decision())

    def test_put_uses_correct_collection_path(self) -> None:
        transport = FakeHttpTransport()
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )

        source.put("sim-path", _decision("sim-path"))

        method, url, _ = transport.calls[0]
        assert f"/{COLLECTION_DECISIONS}/sim-path" in url
        assert "retailtwin-ai-511002" in url
        assert "databases/(default)/documents" in url

    def test_put_stores_decision_hash_in_document(self) -> None:
        transport = FakeHttpTransport()
        source = FirestoreDecisionSource(
            transport=transport, token_provider=_FakeToken()
        )
        decision = _decision("sim-hash")
        source.put("sim-hash", decision)
        # First call is GET (read for CAS), second is PATCH (write).
        get_call, patch_call = transport.calls
        assert get_call[0] == "GET"
        assert patch_call[0] == "PATCH"
        doc = json.loads(patch_call[2].decode())  # type: ignore[union-attr]
        assert "decision_hash" in doc["fields"]
        expected_hash = FirestoreDecisionSource._decision_hash(decision)
        assert doc["fields"]["decision_hash"]["stringValue"] == expected_hash


class TestFirestoreDecisionSourceAvailable:
    def test_available_is_true_when_constructed(self) -> None:
        source = FirestoreDecisionSource(
            transport=FakeHttpTransport(), token_provider=_FakeToken()
        )
        assert source.available is True