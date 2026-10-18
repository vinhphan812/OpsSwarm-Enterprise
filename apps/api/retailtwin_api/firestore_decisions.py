"""Firestore-backed ``DecisionSource`` (ADR 0024).

Stores Decisions as JSON in Firestore documents at
``/decision_records/{simulation_id}``. The document has three fields:

* ``simulation_id`` (``stringValue``) — the Firestore Decision id.
* ``decision_json`` (``stringValue``) — JSON-encoded ``Decision`` payload.
* ``decision_hash`` (``stringValue``) — SHA-256 of the JSON-encoded payload.
  Used as a CAS token to detect overwrites with a different payload.

Writes use compare-and-swap (CAS): ``put`` reads the existing document,
computes its hash, and issues a conditional update that only succeeds
when the stored hash is absent (first write) or matches the value
observed at read time. A different payload for the same ``simulation_id``
raises ``DecisionConflict`` so the caller treats it as a non-terminal
outcome rather than silently overwriting evidence from an earlier run.

Reads (``GET /decision_records/{simulation_id}``) return ``None`` for
``HTTP 404``. Network errors and unexpected HTTP statuses raise
:class:`DecisionStoreUnavailable`; the surrounding code treats that as a
typed failure (``insufficient_evidence`` or ``provider_failed``) and never
silently falls back to process memory.

No model reasoning, prompts, or credentials are stored. Only the canonical
``Decision`` Pydantic model is serialized via ``model_dump_json``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Protocol as TypingProtocol

from retailtwin_api.contracts import Decision
from retailtwin_api.firestore_twin import (
    ALLOWED_PROJECT,
    HttpTransport,
    TwinUnavailable,
    UrllibTransport,
)

log = logging.getLogger(__name__)

# Firestore scopes — read/write access to the (default) database is the same
# scope the LiveTwinRepository uses, so a deploy that already grants the SA
# roles/datastore.user does not need a second binding.
_FIRESTORE_SCOPE = "https://www.googleapis.com/auth/datastore"

# Document collection — separate from the Live Twin /stores and /inventory
# collections. Auxiliary state lives in its own top-level collection so a
# wipe of the Live Twin never touches Decisions and vice versa.
COLLECTION_DECISIONS = "decision_records"


class DecisionStoreUnavailable(RuntimeError):
    """Firestore decision storage is unreachable or rejected the write."""


class DecisionConflict(RuntimeError):
    """A different Decision payload is already stored for this simulation_id.

    Raised when ``put`` detects that the stored ``decision_hash`` does not
    match the hash of the payload being written. The caller must treat this
    as a non-terminal outcome and never silently overwrite evidence from an
    earlier run.
    """


class TokenProvider(TypingProtocol):
    def __call__(self) -> str: ...


class _ApplicationDefaultTokenProvider:
    """Application Default Credentials access token (per ADR 0020).

    Caches the credentials object across calls. Refreshes when expired. A
    missing ADC raises :class:`DecisionStoreUnavailable` so the production
    composition root can refuse to start a Cloud Run instance that has no
    Firestore access.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._credentials: Any = None

    def __call__(self) -> str:
        with self._lock:
            try:
                if self._credentials is None:
                    import google.auth

                    self._credentials, _ = google.auth.default(scopes=[_FIRESTORE_SCOPE])
                if not self._credentials.valid:
                    self._credentials.refresh(_UrllibAuthRequest())
                token = self._credentials.token
            except DecisionStoreUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 — surface any ADC failure
                raise DecisionStoreUnavailable(
                    f"Application Default Credentials are not available: {type(exc).__name__}"
                ) from None
        if not token or any(c in token for c in "\n\r\t "):
            raise DecisionStoreUnavailable("Access token for decision store is invalid.")
        return str(token)


class _UrllibAuthResponse:
    __slots__ = ("status", "headers", "data")

    def __init__(self, status: int, headers: Mapping[str, str], data: bytes) -> None:
        self.status = status
        self.headers = headers
        self.data = data


class _UrllibAuthRequest:
    """A google-auth transport on urllib, so refreshing a token needs no extra HTTP library."""

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        **_: Any,
    ) -> _UrllibAuthResponse:
        request = urllib.request.Request(
            url, data=body, method=method, headers=dict(headers or {})
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or 10) as response:
                return _UrllibAuthResponse(response.status, dict(response.headers), response.read())
        except urllib.error.HTTPError as exc:
            return _UrllibAuthResponse(exc.code, dict(exc.headers or {}), exc.read())


TokenProviderFactory = Callable[[], TokenProvider]


def _default_token_provider_factory() -> TokenProvider:
    return _ApplicationDefaultTokenProvider()


class FirestoreDecisionSource:
    """Cross-instance ``DecisionSource`` backed by a Firestore collection.

    Production wiring: ``FirestoreDecisionSource()``. Tests inject a fake
    transport and a fake token provider so no network is required.
    """

    def __init__(
        self,
        project: str = ALLOWED_PROJECT,
        transport: HttpTransport | None = None,
        token_provider: TokenProvider | None = None,
    ) -> None:
        self._project = project
        self._transport = transport if transport is not None else UrllibTransport()
        self._tokens = token_provider if token_provider is not None else _ApplicationDefaultTokenProvider()

    @property
    def available(self) -> bool:
        return True

    @staticmethod
    def _decision_hash(decision: Decision) -> str:
        """Stable SHA-256 hash of the canonical JSON form."""
        canonical = decision.model_dump_json()
        return hashlib.sha256(canonical.encode()).hexdigest()

    def put(self, simulation_id: str, decision: Decision) -> None:
        decision_json = decision.model_dump_json()
        decision_hash = self._decision_hash(decision)

        # Read-modify-write CAS: detect conflicting payloads before writing.
        response = self._call("GET", self._doc_url(simulation_id), None)
        if response.status == 404:
            # First write: create with no precondition (document does not exist).
            body = {
                "fields": {
                    "simulation_id": {"stringValue": simulation_id},
                    "decision_json": {"stringValue": decision_json},
                    "decision_hash": {"stringValue": decision_hash},
                }
            }
            write_resp = self._call("PATCH", self._doc_url(simulation_id), body)
            if write_resp.status not in (200, 201):
                raise DecisionStoreUnavailable(
                    f"Firestore PATCH decision_records/{simulation_id} returned HTTP {write_resp.status}"
                )
            return
        if response.status != 200:
            raise DecisionStoreUnavailable(
                f"Firestore GET decision_records/{simulation_id} returned HTTP {response.status}"
            )
        # Existing document: extract the stored hash and compare.
        existing_hash = self._extract_hash(response.body)
        if existing_hash is not None and existing_hash != decision_hash:
            raise DecisionConflict(
                f"Decision for simulation_id={simulation_id!r} already exists "
                f"with a different payload (hash mismatch). "
                "Cannot overwrite evidence from an earlier run. "
                "Read the existing record and resolve the conflict manually."
            )
        # Same hash (idempotent retry) or no hash field (legacy doc): overwrite.
        body = {
            "fields": {
                "simulation_id": {"stringValue": simulation_id},
                "decision_json": {"stringValue": decision_json},
                "decision_hash": {"stringValue": decision_hash},
            }
        }
        write_resp = self._call("PATCH", self._doc_url(simulation_id), body)
        if write_resp.status not in (200, 201):
            raise DecisionStoreUnavailable(
                f"Firestore PATCH decision_records/{simulation_id} returned HTTP {write_resp.status}"
            )

    def get_for_simulation(self, simulation_id: str) -> Decision | None:
        response = self._call("GET", self._doc_url(simulation_id), None)
        if response.status == 404:
            return None
        if response.status != 200:
            raise DecisionStoreUnavailable(
                f"Firestore GET decision_records/{simulation_id} returned HTTP {response.status}"
            )
        return self._parse(response.body, simulation_id)

    # --- internal -----------------------------------------------------------

    def _doc_url(self, simulation_id: str) -> str:
        return (
            f"https://firestore.googleapis.com/v1/projects/{self._project}"
            f"/databases/(default)/documents/{COLLECTION_DECISIONS}/{simulation_id}"
        )

    def _call(self, method: str, url: str, payload: dict[str, Any] | None):
        body_bytes = None if payload is None else json.dumps(payload).encode("utf-8")
        try:
            token = self._tokens()
        except DecisionStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — surface any token failure
            raise DecisionStoreUnavailable(
                f"Decision-store access token unavailable: {type(exc).__name__}"
            ) from exc
        if not token or any(c in token for c in "\n\r\t "):
            raise DecisionStoreUnavailable("Decision-store access token is malformed.")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            return self._transport.request(method, url, body_bytes, headers)
        except TwinUnavailable:
            raise DecisionStoreUnavailable("Firestore decision store is unreachable.") from None
        except Exception as exc:  # noqa: BLE001 — surface any transport failure
            raise DecisionStoreUnavailable(
                f"Firestore decision store transport failed: {exc}"
            ) from exc

    @staticmethod
    def _extract_hash(body: str) -> str | None:
        """Extract ``decision_hash`` from a Firestore GET response body."""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        fields = payload.get("fields", {})
        if not isinstance(fields, dict):
            return None
        hash_field = fields.get("decision_hash")
        if not isinstance(hash_field, dict):
            return None
        value = hash_field.get("stringValue")
        return value if isinstance(value, str) else None

    @staticmethod
    def _parse(body: str, simulation_id: str) -> Decision | None:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            log.warning("firestore_decisions.malformed_json sim=%s", simulation_id)
            return None
        if not isinstance(payload, dict):
            return None
        fields = payload.get("fields", {})
        if not isinstance(fields, dict):
            return None
        decision_field = fields.get("decision_json")
        if not isinstance(decision_field, dict):
            return None
        raw = decision_field.get("stringValue")
        if not isinstance(raw, str):
            return None
        try:
            return Decision.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 — invalid stored Decision
            log.warning(
                "firestore_decisions.invalid_decision sim=%s error=%s",
                simulation_id,
                type(exc).__name__,
            )
            return None


__all__ = [
    "COLLECTION_DECISIONS",
    "DecisionConflict",
    "DecisionStoreUnavailable",
    "FirestoreDecisionSource",
    "TokenProvider",
]