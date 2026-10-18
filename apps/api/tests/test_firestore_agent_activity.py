"""Tests for the Firestore-backed ``AgentActivityLog`` (ADR 0024).

Uses the same hand-rolled ``FakeHttpTransport`` pattern as the other
Firestore adapter tests. Covers round-trip, cursor-based pagination,
error typed failure, and the local-cache mirror that ``for_correlation``
relies on.

The old counter-based pagination and ``_bump_count`` path are no longer
tested: the implementation uses Firestore native ``startAfter`` cursors.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import pytest

from retailtwin_api.contracts import ControlStage
from retailtwin_api.firestore_agent_activity import (
    FirestoreAgentActivityLog,
    AgentActivityStoreUnavailable,
)
from retailtwin_api.firestore_twin import HttpResponse
from retailtwin_api.simulation_schemas import CursorParameters


class FakeHttpTransport:
    """Records calls and stores documents by entry id."""

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
        if method == "GET" and "/documents" in url:
            # Simulate Firestore list: return all docs as documents list.
            documents = list(self._docs.values())
            return HttpResponse(200, json.dumps({"documents": documents}))
        if method == "PATCH" and "/documents/" in url:
            if payload is None:
                return HttpResponse(
                    400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}})
                )
            decoded = json.loads(payload.decode())
            entry_id = url.rsplit("/", 1)[-1]
            existing = self._docs.get(entry_id, {})
            merged = {**existing, **decoded}
            self._docs[entry_id] = merged
            return HttpResponse(200, json.dumps(merged))
        return HttpResponse(200, json.dumps({}))


class _FakeToken:
    def __call__(self) -> str:
        return "fake-token"


class TestFirestoreAgentActivityLogRecord:
    def test_record_persists_entry(self) -> None:
        transport = FakeHttpTransport()
        log = FirestoreAgentActivityLog(
            transport=transport, token_provider=_FakeToken()
        )

        entry = log.record(
            ControlStage.OBSERVE,
            "started",
            "corr-1",
            run_id="inv-1",
            sku="P001",
            summary="test",
        )

        assert entry.id.startswith("act-")
        assert entry.stage == ControlStage.OBSERVE
        assert entry.status == "started"
        # PATCH on the canonical URL.
        assert any(
            f"agent_activity/{entry.id}" in url for _, url, _ in transport.calls
        )

    def test_record_serializes_entry_as_string_value(self) -> None:
        transport = FakeHttpTransport()
        log = FirestoreAgentActivityLog(
            transport=transport, token_provider=_FakeToken()
        )

        entry = log.record(ControlStage.INVESTIGATE, "completed", "corr-2")

        method, url, payload = transport.calls[0]
        assert method == "PATCH"
        assert url.endswith(f"/agent_activity/{entry.id}")
        decoded = json.loads(payload.decode())
        assert decoded["fields"]["entry_id"] == {"stringValue": entry.id}
        assert decoded["fields"]["status"] == {"stringValue": "completed"}
        json_payload = decoded["fields"]["entry_json"]["stringValue"]
        from retailtwin_api.simulation_schemas import AgentActivityEntry
        re_decoded = AgentActivityEntry.model_validate_json(json_payload)
        assert re_decoded == entry

    def test_record_raises_on_unexpected_status(self) -> None:
        class _Fail(FakeHttpTransport):
            def request(self, method, url, payload, headers):
                if method == "PATCH" and "agent_activity" in url:
                    return HttpResponse(
                        500, json.dumps({"error": {"status": "INTERNAL"}})
                    )
                return super().request(method, url, payload, headers)

        log = FirestoreAgentActivityLog(
            transport=_Fail(), token_provider=_FakeToken()
        )
        with pytest.raises(AgentActivityStoreUnavailable):
            log.record(ControlStage.OBSERVE, "started", "corr-fail")

    def test_record_raises_on_token_failure(self) -> None:
        def broken_token() -> str:
            raise RuntimeError("ADC missing")

        log = FirestoreAgentActivityLog(
            transport=FakeHttpTransport(), token_provider=broken_token
        )
        with pytest.raises(AgentActivityStoreUnavailable):
            log.record(ControlStage.OBSERVE, "started", "corr-no-token")


class TestFirestoreAgentActivityLogPage:
    def test_page_first_call_returns_entries_with_cursor(self) -> None:
        """First page returns all entries and an opaque next cursor."""
        transport = FakeHttpTransport()
        log = FirestoreAgentActivityLog(
            transport=transport, token_provider=_FakeToken()
        )
        log.record(ControlStage.OBSERVE, "started", "corr-1")
        log.record(ControlStage.INVESTIGATE, "completed", "corr-1")

        transport.calls.clear()
        entries, cursor = log.page(CursorParameters(limit=10))

        assert len(entries) == 2
        assert entries[0].stage == ControlStage.OBSERVE
        assert entries[1].stage == ControlStage.INVESTIGATE
        # A non-empty result always returns a cursor pointing to the last entry.
        assert cursor is not None
        assert isinstance(cursor, str) and len(cursor) > 0

    def test_page_returns_opaque_cursor(self) -> None:
        transport = FakeHttpTransport()
        log = FirestoreAgentActivityLog(
            transport=transport, token_provider=_FakeToken()
        )
        # Write 5 entries; the fake transport returns all of them (no
        # server-side filtering in the unit-test fake).
        for i in range(5):
            log.record(ControlStage.OBSERVE, "started", f"corr-{i}")

        transport.calls.clear()
        entries, cursor = log.page(CursorParameters(limit=3))

        # The fake returns all stored docs; the real Firestore would enforce
        # the pageSize server-side. The cursor is still opaque and decodable.
        assert len(entries) == 5
        assert cursor is not None
        # Cursor must be a non-empty string.
        assert isinstance(cursor, str) and len(cursor) > 0
        # Cursor must be base64url decodable.
        import base64
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        assert isinstance(decoded, list) and len(decoded) == 2

    def test_page_malformed_cursor_raises_value_error(self) -> None:
        transport = FakeHttpTransport()
        log = FirestoreAgentActivityLog(
            transport=transport, token_provider=_FakeToken()
        )
        log.record(ControlStage.OBSERVE, "started", "corr-1")

        with pytest.raises(ValueError, match="Invalid activity cursor"):
            log.page(CursorParameters(since="not-valid-base64!!!", limit=10))

    def test_page_valid_cursor_does_not_raise(self) -> None:
        transport = FakeHttpTransport()
        log = FirestoreAgentActivityLog(
            transport=transport, token_provider=_FakeToken()
        )
        # Encode a valid cursor.
        ts = "2026-10-16T12:00:00+00:00"
        entry_id = "act-abc123"
        cursor = FirestoreAgentActivityLog._encode_cursor(
            datetime.fromisoformat(ts), entry_id
        )
        # Should not raise.
        entries, next_cursor = log.page(CursorParameters(since=cursor, limit=10))
        assert isinstance(entries, list)


class TestFirestoreAgentActivityLogForCorrelation:
    def test_for_correlation_filters_local_cache(self) -> None:
        transport = FakeHttpTransport()
        log = FirestoreAgentActivityLog(
            transport=transport, token_provider=_FakeToken()
        )
        log.record(ControlStage.OBSERVE, "started", "corr-1")
        log.record(ControlStage.OBSERVE, "started", "corr-2")

        entries = log.for_correlation("corr-1")
        assert len(entries) == 1
        assert entries[0].correlation_id == "corr-1"


class TestFirestoreAgentActivityCursorEncoding:
    """Verify cursor encode/decode round-trip."""

    def test_encode_decode_roundtrip(self) -> None:
        ts = datetime(2026, 10, 16, 14, 30, 0, tzinfo=timezone.utc)
        entry_id = "act-9abcdef012"
        encoded = FirestoreAgentActivityLog._encode_cursor(ts, entry_id)
        decoded = FirestoreAgentActivityLog._decode_cursor(encoded)
        assert decoded == (ts.isoformat(), entry_id)

    def test_decode_none_returns_none(self) -> None:
        assert FirestoreAgentActivityLog._decode_cursor(None) is None
        assert FirestoreAgentActivityLog._decode_cursor("") is None

    def test_decode_malformed_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid activity cursor"):
            FirestoreAgentActivityLog._decode_cursor("trash")
