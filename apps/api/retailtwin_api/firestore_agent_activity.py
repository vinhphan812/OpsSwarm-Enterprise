"""Firestore-backed ``AgentActivityLog`` (ADR 0024).

Stores one ``AgentActivityEntry`` per document under
``/agent_activity/{entry_id}``. Document fields:

- ``entry_id`` (``stringValue``) — the canonical Activity id.
- ``ts`` (``timestampValue``) — the event timestamp (ISO 8601 string).
- ``stage`` (``stringValue``) — ``ControlStage`` enum value.
- ``status`` (``stringValue``) — ``started`` / ``completed`` / ``failed`` / etc.
- ``correlation_id`` (``stringValue``).
- ``run_id`` / ``decision`` / ``simulation_id`` / ``focus`` / ``summary``
  (``stringValue`` or absent when null).
- ``entry_json`` (``stringValue``) — full JSON-encoded
  ``AgentActivityEntry`` payload so a future schema bump is non-breaking.

Pagination is handled entirely by Firestore: ``page()`` uses a
``startAfter`` cursor built from the last document's ``ts`` + ``id``.
The cursor encodes both fields so the sort order (``ts`` ascending, ``id``
ascending) is deterministic across pages. No counter document is needed,
and no client-side slicing or offset arithmetic is performed.
The ``__count__`` counter document is no longer written; the old
``_bump_count`` path is removed.

No model reasoning, prompts, or credentials are stored. Only the
canonical ``AgentActivityEntry`` Pydantic model.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from retailtwin_api.agent_activity import AgentActivityLog
from retailtwin_api.contracts import ControlStage
from retailtwin_api.firestore_decisions import _ApplicationDefaultTokenProvider
from retailtwin_api.firestore_twin import (
    ALLOWED_PROJECT,
    HttpTransport,
    TwinUnavailable,
    UrllibTransport,
)
from retailtwin_api.simulation_schemas import AgentActivityEntry, CursorParameters

log = logging.getLogger(__name__)

COLLECTION_ACTIVITY = "agent_activity"


class AgentActivityStoreUnavailable(RuntimeError):
    """Firestore agent activity storage is unreachable or rejected the write."""


def _entry_doc(entry: AgentActivityEntry) -> dict[str, Any]:
    """Build the Firestore document body for one activity entry."""
    fields: dict[str, Any] = {
        "entry_id": {"stringValue": entry.id},
        "ts": {"timestampValue": entry.ts.isoformat()},
        "stage": {"stringValue": entry.stage.value},
        "status": {"stringValue": entry.status},
        "correlation_id": {"stringValue": entry.correlation_id},
        "entry_json": {"stringValue": entry.model_dump_json()},
    }
    for key, value in (
        ("run_id", entry.run_id),
        ("decision", entry.decision),
        ("simulation_id", entry.simulation_id),
        ("focus", entry.focus),
        ("summary", entry.summary),
    ):
        if value is not None:
            fields[key] = {"stringValue": value}
    return {"fields": fields}


def _parse_entry(doc: dict[str, Any]) -> AgentActivityEntry | None:
    fields = doc.get("fields", {})
    if not isinstance(fields, dict):
        return None
    raw = fields.get("entry_json", {})
    if not isinstance(raw, dict):
        return None
    serialized = raw.get("stringValue")
    if not isinstance(serialized, str):
        return None
    try:
        return AgentActivityEntry.model_validate_json(serialized)
    except Exception as exc:  # noqa: BLE001 — invalid stored entry
        log.warning(
            "firestore_agent_activity.invalid_entry error=%s",
            type(exc).__name__,
        )
        return None


class FirestoreAgentActivityLog(AgentActivityLog):
    """Cross-instance ``AgentActivityLog`` backed by Firestore.

    Behaves like the in-memory adapter for read paths (``page``,
    ``for_correlation``) and writes every entry as a new document.
    Pagination uses Firestore native ``startAfter`` cursors; no counter
    document or client-side slicing is needed.
    """

    def __init__(
        self,
        project: str = ALLOWED_PROJECT,
        transport: HttpTransport | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        super().__init__()
        self._project = project
        self._transport = transport if transport is not None else UrllibTransport()
        self._tokens = token_provider if token_provider is not None else _ApplicationDefaultTokenProvider()

    # The in-memory base class owns ``record``. We replace it here so writes
    # go to Firestore; the inherited ``for_correlation`` works against the
    # local cache that ``page`` populates.
    def record(
        self,
        stage: ControlStage,
        status: str,
        correlation_id: str,
        *,
        run_id: str | None = None,
        decision: str | None = None,
        simulation_id: str | None = None,
        sku: str | None = None,
        shelf_id: str | None = None,
        slot_id: str | None = None,
        summary: str | None = None,
        at: datetime | None = None,
        acquired_at: datetime | None = None,
        verdict: str | None = None,
    ) -> AgentActivityEntry:
        ts = at or datetime.now(timezone.utc)
        entry = AgentActivityEntry(
            id=f"act-{self._new_id()}",
            ts=ts,
            stage=stage,
            status=status,
            correlation_id=correlation_id,
            run_id=run_id,
            decision=decision,
            simulation_id=simulation_id,
            sku=sku,
            shelf_id=shelf_id,
            slot_id=slot_id,
            focus=sku,
            summary=summary,
            acquired_at=acquired_at or ts,
            verdict=verdict,
        )
        body = _entry_doc(entry)
        response = self._call(
            "PATCH", self._doc_url(entry.id), body
        )
        if response.status not in (200, 201):
            raise AgentActivityStoreUnavailable(
                f"Firestore PATCH agent_activity/{entry.id} returned HTTP {response.status}"
            )
        # Mirror the entry in the local cache so ``for_correlation`` works
        # for reads on the same instance.
        with self._lock:
            self._entries.append(entry.model_copy(deep=True))
        return entry.model_copy(deep=True)

    def page(self, cursor: CursorParameters) -> tuple[list[AgentActivityEntry], str | None]:
        # Decode the opaque cursor, which encodes (ts_iso, entry_id).
        decoded = self._decode_cursor(cursor.since)
        url = self._collection_url(limit=cursor.limit, after=decoded)
        response = self._call("GET", url, None)
        if response.status != 200:
            raise AgentActivityStoreUnavailable(
                f"Firestore list agent_activity returned HTTP {response.status}"
            )
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise AgentActivityStoreUnavailable(
                "Firestore list response was not JSON."
            ) from exc
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        entries: list[AgentActivityEntry] = []
        for entry_doc in documents:
            if not isinstance(entry_doc, dict):
                continue
            parsed = _parse_entry(entry_doc)
            if parsed is not None:
                entries.append(parsed)
        # entries are returned in insertion order (sorted by Firestore or by id).
        entries.sort(key=lambda item: (item.ts, item.id))
        # Populate the local cache so ``for_correlation`` finds these entries.
        with self._lock:
            self._entries = entries
        if not entries:
            return [], None
        last = entries[-1]
        next_cursor = self._encode_cursor(last.ts, last.id)
        return [item.model_copy(deep=True) for item in entries], next_cursor

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _doc_url(self, entry_id: str) -> str:
        return (
            f"https://firestore.googleapis.com/v1/projects/{self._project}"
            f"/databases/(default)/documents/{COLLECTION_ACTIVITY}/{entry_id}"
        )

    def _collection_url(self, *, limit: int | None = None, after: tuple[str, str] | None = None) -> str:
        params: list[str] = []
        if limit is not None:
            params.append(f"pageSize={limit}")
        if after is not None:
            ts_val, id_val = after
            # Firestore REST API: encode cursor values as JSON, base64url them.
            import base64
            cursor_val = f'"{ts_val}","{id_val}"'
            encoded = base64.urlsafe_b64encode(cursor_val.encode()).decode().rstrip("=")
            params.append(f"startAt={encoded}")
        qs = "&".join(params)
        base = (
            f"https://firestore.googleapis.com/v1/projects/{self._project}"
            f"/databases/(default)/documents/{COLLECTION_ACTIVITY}"
        )
        return base if not qs else f"{base}?{qs}"

    @staticmethod
    def _encode_cursor(ts: datetime, entry_id: str) -> str:
        """Encode (ts_iso, entry_id) as a compact opaque string.

        Uses URL-safe base64 of the JSON array so the cursor can be passed
        as a query parameter value without escaping issues.
        """
        import base64
        import json
        raw = json.dumps([ts.isoformat(), entry_id])
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
        """Decode an opaque cursor back to (ts_iso, entry_id).

        Returns None for a None or empty cursor (start from the beginning).
        Raises ``ValueError`` for a malformed cursor so callers return a
        typed 400.
        """
        if not cursor:
            return None
        try:
            import base64
            import json
            # Re-add padding stripped by _encode_cursor.
            padded = cursor + "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(padded.encode()).decode()
            parsed: list[str] = json.loads(raw)
            if not isinstance(parsed, list) or len(parsed) != 2:
                raise ValueError(f"malformed cursor: {cursor!r}")
            ts_val, id_val = parsed
            if not isinstance(ts_val, str) or not isinstance(id_val, str):
                raise ValueError(f"malformed cursor types: {cursor!r}")
            return (ts_val, id_val)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Invalid activity cursor value {cursor!r}: {exc}. "
                "Use the cursor returned by the previous page response."
            ) from None

    def _call(self, method: str, url: str, payload: dict[str, Any] | None):
        body_bytes = None if payload is None else json.dumps(payload).encode("utf-8")
        try:
            token = self._tokens()
        except AgentActivityStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — surface any token failure
            raise AgentActivityStoreUnavailable(
                f"Agent-activity access token unavailable: {type(exc).__name__}"
            ) from exc
        if not token or any(c in token for c in "\n\r\t "):
            raise AgentActivityStoreUnavailable("Agent-activity access token is malformed.")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            return self._transport.request(method, url, body_bytes, headers)
        except TwinUnavailable:
            raise AgentActivityStoreUnavailable(
                "Firestore agent activity store is unreachable."
            ) from None
        except Exception as exc:  # noqa: BLE001 — surface any transport failure
            raise AgentActivityStoreUnavailable(
                f"Firestore agent activity store transport failed: {exc}"
            ) from exc

    def _new_id(self) -> str:
        import uuid

        return uuid.uuid4().hex[:12]


__all__ = [
    "COLLECTION_ACTIVITY",
    "FirestoreAgentActivityLog",
    "AgentActivityStoreUnavailable",
]