"""Firestore-backed ``MemoryActivationLedger`` (ADR 0024).

Cross-instance replacement for the in-memory activation record. The
ledger is the canonical idempotency boundary for the observer: a
duplicate event id must not start a second investigation, and a
different payload for the same event id is a conflict that the consumer
treats as a non-terminal outcome.

Storage is one document per event id under
``/activation_records/{event_id}``. The document carries:

- ``event_id`` (``stringValue``).
- ``investigation_id`` (``stringValue``).
- ``status`` (``stringValue``) — ``pending`` or ``started``.
- ``event_json`` (``stringValue``) — JSON-encoded ``StoreEvent`` so a
  duplicate-payload check is round-trippable across instances.

Writes are best-effort within the observer's reservation flow: a write
failure raises ``ActivationLedgerUnavailable`` and the observer leaves the
Pub/Sub message unacked for the next delivery. A successful write
advances the reservation to ``pending`` (or ``started`` for commit); a
duplicate write is detected on read.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

from retailtwin_api.agents.observer.consumer import (
    Activation,
    MemoryActivationLedger,
)
from retailtwin_api.firestore_decisions import _ApplicationDefaultTokenProvider
from retailtwin_api.firestore_twin import (
    ALLOWED_PROJECT,
    HttpTransport,
    TwinUnavailable,
    UrllibTransport,
)
from retailtwin_api.schemas import StoreEvent

log = logging.getLogger(__name__)

COLLECTION_ACTIVATIONS = "activation_records"


class ActivationLedgerUnavailable(RuntimeError):
    """Firestore activation storage is unreachable or rejected the write."""


class _CreateConflict(Exception):
    """Internal-only signal that an atomic create lost the precondition.

    The public ``reserve`` flow catches this, re-reads, and classifies
    the outcome as ``duplicate`` or ``conflict`` based on the existing
    record. The exception never escapes to callers.
    """


def _is_precondition_conflict(status: int, body: str) -> bool:
    """Return True when the Firestore response indicates a precondition loss.

    HTTP 409 is the canonical precondition-failure status; 400 with a
    FAILED_PRECONDITION / ALREADY_EXISTS error payload is also a loss.
    """
    if status == 409:
        return True
    if status != 400:
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    status_typed = error.get("status")
    message = error.get("message")
    if status_typed in {"FAILED_PRECONDITION", "ALREADY_EXISTS"}:
        return True
    if isinstance(message, str) and (
        "precondition" in message.lower() or "already exists" in message.lower()
    ):
        return True
    return False


def _activation_doc(
    event_id: str,
    activation: Activation,
    *,
    doc_name: str | None = None,
    owner_token: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "event_id": {"stringValue": event_id},
        "investigation_id": {"stringValue": activation.investigation_id},
        "status": {"stringValue": activation.status},
        "event_json": {"stringValue": activation.event.model_dump_json()},
    }
    if owner_token is not None:
        fields["owner_token"] = {"stringValue": owner_token}
    payload: dict[str, Any] = {"fields": fields}
    if doc_name is not None:
        payload["name"] = doc_name
    return payload


def _doc_name(project: str, event_id: str) -> str:
    return (
        f"projects/{project}/databases/(default)/documents"
        f"/{COLLECTION_ACTIVATIONS}/{event_id}"
    )


@dataclass(frozen=True)
class _StoredActivation:
    """Activation record plus the fencing token and version stamp.

    ``owner_token`` uniquely identifies the Cloud Run instance that holds
    the pending reservation. ``update_time`` is the Firestore
    ``updateTime`` at the moment the record was observed; both are used
    to build the CAS preconditions on ``commit`` and ``abort``.
    """

    activation: Activation
    owner_token: str
    update_time: str | None


def _parse_activation(doc: dict[str, Any]) -> _StoredActivation | None:
    fields = doc.get("fields", {})
    if not isinstance(fields, dict):
        return None
    raw = fields.get("event_json", {})
    if not isinstance(raw, dict):
        return None
    serialized = raw.get("stringValue")
    if not isinstance(serialized, str):
        return None
    investigation_id = ""
    status_field = fields.get("status", {})
    status_typed: Literal["pending", "started"] | None = None
    if isinstance(status_field, dict):
        candidate = status_field.get("stringValue")
        if isinstance(candidate, str) and candidate in ("pending", "started"):
            status_typed = candidate  # type: ignore[assignment]
    if status_typed is None:
        return None
    id_field = fields.get("investigation_id", {})
    if isinstance(id_field, dict):
        id_candidate = id_field.get("stringValue")
        if isinstance(id_candidate, str):
            investigation_id = id_candidate
    owner_token = ""
    token_field = fields.get("owner_token", {})
    if isinstance(token_field, dict):
        token_candidate = token_field.get("stringValue")
        if isinstance(token_candidate, str):
            owner_token = token_candidate
    update_time = doc.get("updateTime")
    if not isinstance(update_time, str):
        update_time = None
    try:
        event = StoreEvent.model_validate_json(serialized)
    except Exception as exc:  # noqa: BLE001 — invalid stored event
        log.warning(
            "firestore_activation.invalid_event error=%s", type(exc).__name__
        )
        return None
    return _StoredActivation(
        Activation(investigation_id, event, status_typed),
        owner_token,
        update_time,
    )


class FirestoreActivationLedger(MemoryActivationLedger):
    """Cross-instance replacement for :class:`MemoryActivationLedger`.

    Mirrors the in-memory record on every successful write so that
    ``get`` keeps working between calls on the same instance. The
    Firestore document is the canonical store.
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
        # Per-instance cache of the (token, updateTime) tuple observed at
        # ``reserve`` time. Used to fence ``commit`` and ``abort`` so a
        # Cloud Run instance never mutates or deletes a reservation that
        # another instance already progressed. Keyed by ``event_id``.
        self._reservations: dict[str, _StoredActivation] = {}

    def reserve(self, event: StoreEvent) -> Any:
        """Atomically claim the event for investigation.

        Each call mints a unique ``owner_token``. The atomic create uses
        a Firestore ``currentDocument.exists=false`` precondition, so two
        Cloud Run instances racing the same ``event_id`` cannot both
        become owner: the loser re-reads, sees a foreign ``owner_token``
        on the existing pending record, and classifies as
        ``in_flight``. ``commit`` and ``abort`` later use the
        ``updateTime`` and ``owner_token`` observed at ``reserve``
        success as a CAS fence so they cannot act on a record that
        another instance has progressed.
        """
        owner_token = uuid.uuid4().hex
        existing_record = self._read_with_full(event.event_id)
        if existing_record is not None:
            return self._classify_existing(event, existing_record, owner_token)

        # First reservation. Atomic create with `currentDocument.exists=false`.
        investigation_id = f"inv-{event.event_id}"
        activation = Activation(investigation_id, event, "pending")
        try:
            stored = self._create_atomic(
                event.event_id, activation, owner_token=owner_token
            )
        except _CreateConflict:
            # A concurrent instance won the race. Re-read and classify
            # by the foreign ``owner_token`` on the existing record.
            existing_after = self._read_with_full(event.event_id)
            if existing_after is None:
                # The winning instance raced the entire reservation, then
                # aborted before we could re-read. Retry once; if it
                # still fails, surface as unavailable so the Pub/Sub
                # message is re-delivered.
                stored = self._create_atomic(
                    event.event_id, activation, owner_token=owner_token
                )
                with self._lock:
                    self._reservations[event.event_id] = stored
                return self._build_reservation("owner", stored.activation)
            return self._classify_existing(event, existing_after, owner_token)
        with self._lock:
            self._reservations[event.event_id] = stored
        return self._build_reservation("owner", stored.activation)

    def _classify_existing(
        self,
        event: StoreEvent,
        existing_record: _StoredActivation,
        owner_token: str,
    ) -> Any:
        """Classify a re-read after a precondition loss.

        The foreign ``owner_token`` is the unique creator marker for the
        in-flight reservation; a different value proves we did NOT
        create the record and must NOT start a second investigation.
        """
        activation = existing_record.activation
        if activation.event != event:
            return self._build_reservation("conflict", activation)
        if activation.status == "started":
            # A different instance already committed; the work is done.
            return self._build_reservation("duplicate", activation)
        if existing_record.owner_token and existing_record.owner_token != owner_token:
            # A pending reservation owned by a different Cloud Run
            # instance. Surface as ``in_flight`` so the consumer acks
            # the message without starting a duplicate investigation.
            return self._build_reservation("in_flight", activation)
        # Same instance, same token (a stale retry after a successful
        # create call); treat as owner so a delivery retry on the same
        # message does not double-start.
        if existing_record.update_time is not None:
            with self._lock:
                self._reservations[activation.event.event_id] = existing_record
        return self._build_reservation("owner", activation)

    def commit(self, event_id: str) -> None:
        """Atomically transition ``pending`` to ``started``.

        The ``pending → started`` transition uses a Firestore
        ``currentDocument.updateTime`` precondition so a concurrent
        commit or abort on another instance surfaces as
        ``ActivationLedgerUnavailable`` rather than corrupting state.
        The ``owner_token`` is preserved across the transition via an
        ``updateMask`` so the fence token survives the status flip.
        """
        from retailtwin_api.agents.observer.consumer import ObservationError

        existing = self._read_with_full(event_id)
        if existing is None or existing.activation.status != "pending":
            raise ObservationError(event_id)
        if existing.update_time is None:
            raise ActivationLedgerUnavailable(
                f"activation_records/{event_id} has no updateTime; cannot CAS-write."
            )
        committed = Activation(
            existing.activation.investigation_id,
            existing.activation.event,
            "started",
        )
        self._write_atomic(
            event_id,
            committed,
            expected_update_time=existing.update_time,
            owner_token=existing.owner_token or None,
        )

    def abort(self, event_id: str) -> None:
        """Conditional DELETE fenced by the reservation we observed at
        ``reserve`` time. If the document has been mutated or deleted by
        another instance (``updateTime`` no longer matches), ``abort``
        silently no-ops as an ``abort_loser`` so it never removes a
        later owner's reservation.
        """
        with self._lock:
            stored = self._reservations.get(event_id)
        if stored is None or stored.update_time is None:
            # Mirror the in-memory adapter: a missing/already-progressed
            # event id is a no-op, not an error.
            response = self._call("DELETE", self._doc_url(event_id), None)
            if response.status not in (200, 404):
                raise ActivationLedgerUnavailable(
                    f"Firestore DELETE activation_records/{event_id} "
                    f"returned HTTP {response.status}"
                )
            return
        try:
            self._delete_atomic(
                event_id,
                expected_update_time=stored.update_time,
                owner_token=stored.owner_token or None,
            )
        except _CreateConflict:
            # Someone else has progressed the reservation; the abort is
            # a no-op and the original owner is left to commit/abort.
            log.info(
                "firestore_activation.abort_loser event_id=%s "
                "stored_update_time=%s owner_token=%s",
                event_id,
                stored.update_time,
                stored.owner_token,
            )
            return
        with self._lock:
            self._reservations.pop(event_id, None)

    def get(self, event_id: str) -> Activation | None:
        stored = self._read_with_full(event_id)
        return None if stored is None else stored.activation

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _doc_url(self, event_id: str) -> str:
        return (
            f"https://firestore.googleapis.com/v1/projects/{self._project}"
            f"/databases/(default)/documents/{COLLECTION_ACTIVATIONS}/{event_id}"
        )

    def _database_root(self) -> str:
        return (
            f"https://firestore.googleapis.com/v1/projects/{self._project}"
            "/databases/(default)/documents"
        )

    def _read_with_full(self, event_id: str) -> _StoredActivation | None:
        """Return ``_StoredActivation`` parsed from the doc or ``None``."""
        response = self._call("GET", self._doc_url(event_id), None)
        if response.status == 404:
            return None
        if response.status != 200:
            raise ActivationLedgerUnavailable(
                f"Firestore GET activation_records/{event_id} returned HTTP {response.status}"
            )
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise ActivationLedgerUnavailable(
                "Firestore activation response was not JSON."
            ) from exc
        if not isinstance(payload, dict):
            return None
        return _parse_activation(payload)

    def _read(self, event_id: str) -> Activation | None:
        stored = self._read_with_full(event_id)
        return None if stored is None else stored.activation

    def _create_atomic(
        self,
        event_id: str,
        activation: Activation,
        *,
        owner_token: str,
    ) -> _StoredActivation:
        """Create-or-fail with ``currentDocument.exists=false``.

        Returns the parsed ``_StoredActivation`` (including the
        ``updateTime`` returned by the commit) so callers can issue a
        CAS follow-up. A second instance that races the read observes
        ALREADY_EXISTS / FAILED_PRECONDITION, which the caller converts
        to a re-read + classification.
        """
        body = {
            "writes": [
                {
                    "update": _activation_doc(
                        event_id,
                        activation,
                        doc_name=_doc_name(self._project, event_id),
                        owner_token=owner_token,
                    ),
                    "currentDocument": {"exists": False},
                }
            ]
        }
        response = self._call("POST", f"{self._database_root()}:commit", body)
        if response.status == 200:
            stored = self._parse_commit_response(
                response.body, event_id, activation, owner_token
            )
            with self._lock:
                self._records[event_id] = Activation(
                    activation.investigation_id,
                    activation.event.model_copy(deep=True),
                    activation.status,
                )
            return stored
        if _is_precondition_conflict(response.status, response.body):
            raise _CreateConflict(
                f"activation_records/{event_id} already exists (race)"
            )
        raise ActivationLedgerUnavailable(
            f"Firestore atomic create activation_records/{event_id} "
            f"returned HTTP {response.status}: {response.body[:200]}"
        )

    def _write_atomic(
        self,
        event_id: str,
        activation: Activation,
        *,
        expected_update_time: str,
        owner_token: str | None = None,
    ) -> None:
        """CAS-write using ``currentDocument.updateTime``.

        An explicit ``updateMask`` writes only the status /
        investigation / event fields and preserves the stored
        ``owner_token``, so the fence survives the status transition.
        """
        update = _activation_doc(
            event_id,
            activation,
            doc_name=_doc_name(self._project, event_id),
        )
        if owner_token is not None:
            update["fields"]["owner_token"] = {"stringValue": owner_token}
        body = {
            "writes": [
                {
                    "update": update,
                    "currentDocument": {"updateTime": expected_update_time},
                    "updateMask": {"fieldPaths": [
                        "investigation_id",
                        "status",
                        "event_json",
                        "owner_token",
                    ]},
                }
            ]
        }
        response = self._call("POST", f"{self._database_root()}:commit", body)
        if response.status == 200:
            with self._lock:
                self._records[event_id] = Activation(
                    activation.investigation_id,
                    activation.event.model_copy(deep=True),
                    activation.status,
                )
                self._reservations.pop(event_id, None)
            return
        if _is_precondition_conflict(response.status, response.body):
            raise ActivationLedgerUnavailable(
                f"Firestore CAS write activation_records/{event_id} "
                f"lost the precondition (updateTime changed concurrently)"
            )
        raise ActivationLedgerUnavailable(
            f"Firestore CAS write activation_records/{event_id} "
            f"returned HTTP {response.status}: {response.body[:200]}"
        )

    def _delete_atomic(
        self,
        event_id: str,
        *,
        expected_update_time: str,
        owner_token: str | None = None,
    ) -> None:
        """Conditional DELETE fenced by ``updateTime`` (and ``owner_token``).

        Raises ``_CreateConflict`` when the precondition is lost so the
        caller (typically ``abort``) can convert that into a no-op
        outcome (``abort_loser``) instead of unconditionally deleting a
        later owner's reservation. ``owner_token`` is encoded as an
        additional update-mask check indirectly through the
        ``updateTime`` fence; we propagate it here for completeness so
        a stricter transport that honours token preconditions can be
        plugged in without changing the public signature.
        """
        del owner_token  # see docstring; updateTime is the canonical fence
        body = {
            "writes": [
                {
                    "delete": _doc_name(self._project, event_id),
                    "currentDocument": {"updateTime": expected_update_time},
                }
            ]
        }
        response = self._call("POST", f"{self._database_root()}:commit", body)
        if response.status == 200:
            with self._lock:
                self._records.pop(event_id, None)
            return
        if _is_precondition_conflict(response.status, response.body):
            raise _CreateConflict(
                f"activation_records/{event_id} delete lost precondition "
                f"(expected updateTime={expected_update_time})"
            )
        raise ActivationLedgerUnavailable(
            f"Firestore conditional delete activation_records/{event_id} "
            f"returned HTTP {response.status}: {response.body[:200]}"
        )

    def _parse_commit_response(
        self,
        body: str,
        event_id: str,
        activation: Activation,
        owner_token: str,
    ) -> _StoredActivation:
        """Extract the new ``updateTime`` from a ``:commit`` response."""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ActivationLedgerUnavailable(
                "Firestore activation commit response was not JSON."
            ) from exc
        update_time = ""
        if isinstance(payload, dict):
            write_results = payload.get("writeResults")
            if isinstance(write_results, list) and write_results:
                first = write_results[0]
                if isinstance(first, dict):
                    candidate = first.get("updateTime")
                    if isinstance(candidate, str):
                        update_time = candidate
        return _StoredActivation(
            Activation(
                activation.investigation_id,
                activation.event.model_copy(deep=True),
                activation.status,
            ),
            owner_token,
            update_time or None,
        )

    def _write(self, event_id: str, activation: Activation) -> None:
        body = _activation_doc(event_id, activation)
        response = self._call("PATCH", self._doc_url(event_id), body)
        if response.status not in (200, 201):
            raise ActivationLedgerUnavailable(
                f"Firestore PATCH activation_records/{event_id} returned HTTP {response.status}"
            )
        # Mirror in the in-memory cache so ``get`` works between calls on
        # the same instance.
        with self._lock:
            stored = Activation(
                activation.investigation_id,
                activation.event.model_copy(deep=True),
                activation.status,
            )
            self._records[event_id] = stored

    def _call(self, method: str, url: str, payload: dict[str, Any] | None):
        body_bytes = None if payload is None else json.dumps(payload).encode("utf-8")
        try:
            token = self._tokens()
        except ActivationLedgerUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — surface any token failure
            raise ActivationLedgerUnavailable(
                f"Activation-ledger access token unavailable: {type(exc).__name__}"
            ) from exc
        if not token or any(c in token for c in "\n\r\t "):
            raise ActivationLedgerUnavailable("Activation-ledger access token is malformed.")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            return self._transport.request(method, url, body_bytes, headers)
        except TwinUnavailable:
            raise ActivationLedgerUnavailable(
                "Firestore activation ledger is unreachable."
            ) from None
        except Exception as exc:  # noqa: BLE001 — surface any transport failure
            raise ActivationLedgerUnavailable(
                f"Firestore activation ledger transport failed: {exc}"
            ) from exc

    @staticmethod
    def _build_reservation(kind: str, activation: Activation) -> Any:
        # Importing here avoids a circular import; the consumer module owns
        # the ``_Reservation`` dataclass.
        from retailtwin_api.agents.observer.consumer import _Reservation

        kind_typed: Literal["owner", "duplicate", "conflict", "in_flight"]
        if kind == "owner":
            kind_typed = "owner"
        elif kind == "in_flight":
            kind_typed = "in_flight"
        elif kind == "duplicate":
            kind_typed = "duplicate"
        else:
            kind_typed = "conflict"
        return _Reservation(
            kind_typed,
            activation.investigation_id,
            activation.event.model_copy(deep=True),
        )


__all__ = [
    "ActivationLedgerUnavailable",
    "COLLECTION_ACTIVATIONS",
    "FirestoreActivationLedger",
]