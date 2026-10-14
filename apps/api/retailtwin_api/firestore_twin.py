"""Canonical Firestore Live Twin boundary.

Explicit repository boundary with typed reads/writes for the RetailTwin
Live Twin inventory state. Implements bounded versioned mutation/conflict
resolution and deterministic schema/seed/reset interface.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 ARCHITECTURAL NOTES — ISSUE 6 HIERARCHY DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The issue-6 specification mentions "Zone / Shelf / Slot / Product".
This refers to the *physical layout data model* in the UI and simulation,
NOT a Firestore document subcollection hierarchy. Here is why:

  1. The Live Twin mutation boundary operates at the SKU level.
     A bounded action (move product, change facings, replenish) targets
     one SKU and its shelf/slot placement. Deepening the Firestore
     hierarchy to /zones/{z}/shelves/{s}/slots/{sl}/inventory/{sku}
     would require 4 sequential read-modify-write rounds per mutation —
     unnecessary complexity for the bounded action contract.

  2. shelf_id and slot_id ARE present in the InventoryDocument as
     scalar fields (see InventoryDocument.store_id, shelf_id, slot_id).
     The physical location information is not lost — it travels with
     the SKU-level document and is returned in ProductInventory responses.

  3. The Zone / Shelf / Slot hierarchy lives as UI layout metadata
     (apps/web/src/scene/layout.ts, apps/web/src/fixtures/demo/store.ts)
     and is NOT a separate Firestore document collection. The 3D scene
     derives layout from fixture data, not from Firestore.

  4. Real-world retail systems often flatten shelf/slot into the SKU
     record for exactly this reason: a product can be in one slot now
     and moved to another — tracking the slot as a mutable attribute of
     the SKU document (rather than a parent in the hierarchy) matches
     how the domain actually behaves.

  CONFIRMED: Current path is correct for the live twin boundary:
    /stores/{store_id}                        → StoreDocument
    /stores/{store_id}/inventory/{sku}        → InventoryDocument
                                                  fields: sku, shelf_id, slot_id,
                                                  facings, shelf_quantity,
                                                  backroom_quantity, version

  If a future issue requires a full Zone→Shelf→Slot Firestore hierarchy
  (e.g., for analytics, audit, or warehouse-management purposes), it
  should be modeled as a SEPARATE read-only projection, not as the
  mutation boundary for the Live Twin.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Canonical paths:
  - /stores/{store_id}                    – Store-level metadata document
  - /stores/{store_id}/inventory/{sku}    – Per-SKU inventory documents (subcollection)

This module is intentionally isolated from the HTTP routes. The routes
continue to call the StoreRepository interface defined in store.py.

NOTE ON FAKE TRANSPORT: FirestoreLiveTwinRepository is exercised against
FakeFirestoreTransport (defined in test_firestore_twin.py), which fully
simulates the Firestore REST contract including :commit preconditions,
optimistic concurrency, and stale-write rejection. Production auth is
Application Default Credentials (google.auth.default), not a gcloud
executable. Preconditions are exists or updateTime. Real Firestore is not
called in CI. See the test file's FAKE TRANSPORT ARCHITECTURAL DECISION
block for the full rationale.

"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self

from pydantic import BaseModel, Field

from retailtwin_api.errors import ApiError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firestore canonical collection / document paths
# ---------------------------------------------------------------------------

COLLECTION_STORES = "stores"       # /stores/{store_id}
COLLECTION_STORE = COLLECTION_STORES  # backward alias
COLLECTION_GROUP_INVENTORY = "inventory"  # collection group query path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALLOWED_PROJECT = "retailtwin-ai-511002"
ALLOWED_LOCATION = "us-central1"
FIRESTORE_SCOPE = "https://www.googleapis.com/auth/datastore"


class TwinConfigError(Exception):
    """Firestore Live Twin is misconfigured or unavailable."""


@dataclass(frozen=True)
class TwinConfig:
    """Validated Firestore Live Twin configuration.

    project  – GCP project holding the Firestore database
    location – Firestore database region
    """

    project: str = ALLOWED_PROJECT
    location: str = ALLOWED_LOCATION

    def validated(self) -> Self:
        if self.project != ALLOWED_PROJECT:
            raise TwinConfigError(
                f"Refusing project {self.project}. Live Twin stays on {ALLOWED_PROJECT}."
            )
        return self


# ---------------------------------------------------------------------------
# HTTP transport (abstracted for test injection)
# ---------------------------------------------------------------------------


class HttpResponse:
    __slots__ = ("status", "body")

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body


class HttpTransport(Protocol):
    """Injectable HTTP transport for Firestore REST calls."""

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse: ...


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class _FirestoreField(BaseModel):
    """One Firestore document field (simplified, string-only subset)."""

    stringValue: str | None = None
    integerValue: str | None = None
    booleanValue: bool | None = None
    timestampValue: str | None = None


class _FirestoreDocument(BaseModel):
    name: str
    fields: dict[str, _FirestoreField] = Field(default_factory=dict)
    createTime: str | None = None
    updateTime: str | None = None


class _FirestoreListResponse(BaseModel):
    documents: list[_FirestoreDocument] = Field(default_factory=list)
    nextPageToken: str | None = None


# ---------------------------------------------------------------------------
# Document schema models (canonical Live Twin state)
# ---------------------------------------------------------------------------


class StoreDocument(BaseModel):
    """Canonical /store/{store_id} document."""

    store_id: str = Field(min_length=1)
    version: str = Field(pattern=r"^v\d+$")
    updated_at: datetime

    def context_version(self) -> str:
        return f"{self.store_id}:{self.version}"


class InventoryDocument(BaseModel):
    """Canonical /stores/{store_id}/inventory/{sku} document."""

    store_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    shelf_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    facings: int = Field(ge=0)
    shelf_quantity: int = Field(ge=0)
    backroom_quantity: int = Field(ge=0)
    version: int = Field(ge=1)
    updated_at: datetime

    def to_product_inventory(self) -> dict[str, Any]:
        return {
            "store_id": self.store_id,
            "sku": self.sku,
            "shelf_id": self.shelf_id,
            "slot_id": self.slot_id,
            "facings": self.facings,
            "shelf_quantity": self.shelf_quantity,
            "backroom_quantity": self.backroom_quantity,
            "version": self.version,
        }


class InventorySeed(BaseModel):
    """Seed data for a single inventory SKU."""

    sku: str = Field(min_length=1)
    shelf_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    facings: int = Field(ge=0)
    shelf_quantity: int = Field(ge=0)
    backroom_quantity: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TwinConflict(Exception):
    """A bounded conflict detected at the Firestore mutation boundary."""

    def __init__(self, sku: str, stored_version: int, incoming_version: int) -> None:
        self.sku = sku
        self.stored_version = stored_version
        self.incoming_version = incoming_version
        super().__init__(
            f"SKU {sku!r} conflict: stored version {stored_version}, "
            f"incoming version {incoming_version}"
        )


class TwinNotFound(Exception):
    """A document was not found in Firestore."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Document not found: {path}")


class TwinUnavailable(Exception):
    """Firestore is unreachable or returned an unexpected error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Live Twin unavailable: {reason}")


# ---------------------------------------------------------------------------
# Firestore REST transport (production)
# ---------------------------------------------------------------------------


class UrllibTransport:
    """Production HTTP transport using the stdlib urllib."""

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        request = urllib.request.Request(
            url, data=payload, headers=dict(headers), method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return HttpResponse(response.status, response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read().decode("utf-8", errors="replace"))
        except urllib.error.URLError as exc:
            raise TwinUnavailable(str(exc.reason)) from exc


def _database_root(project: str) -> str:
    return f"https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents"


def _doc_name(config: TwinConfig, collection: str, *path: str) -> str:
    segments = [collection, *path]
    return f"{_database_root(config.project)}/{'/'.join(segments)}"


def _doc_path(collection: str, *path: str) -> str:
    return f"{collection}/" + "/".join(path)


# ---------------------------------------------------------------------------
# Firestore REST helpers
# ---------------------------------------------------------------------------


def _http_error(action: str, status: int, body: str) -> TwinUnavailable:
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            error = payload.get("error", {})
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return TwinUnavailable(f"{action} failed (HTTP {status}): {error['message']}")
    except json.JSONDecodeError:
        pass
    return TwinUnavailable(f"{action} failed (HTTP {status}): {body[:200]}")


def _precondition_conflict(status: int, body: str) -> bool:
    if status == 409:
        return True
    if status != 400:
        return False
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            error = payload.get("error", {})
            if isinstance(error, dict):
                return error.get("status") in {"FAILED_PRECONDITION", "ALREADY_EXISTS"}
    except json.JSONDecodeError:
        pass
    return False


def _timestamp(value: str) -> datetime:
    """Parse a Firestore timestamp string to aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TwinUnavailable(f"Unreadable timestamp {value!r}.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _string_field(fields: dict[str, _FirestoreField], name: str) -> str:
    f = fields.get(name)
    if f is None or f.stringValue is None:
        raise TwinUnavailable(f"Document field {name!r} is missing or not a string.")
    return f.stringValue


def _int_field(fields: dict[str, _FirestoreField], name: str) -> int:
    f = fields.get(name)
    if f is None or f.integerValue is None:
        raise TwinUnavailable(f"Document field {name!r} is missing or not an integer.")
    try:
        return int(f.integerValue)
    except ValueError as exc:
        raise TwinUnavailable(f"Document field {name!r} is not a valid integer.") from exc


def _bool_field(fields: dict[str, _FirestoreField], name: str) -> bool:
    f = fields.get(name)
    if f is None or f.booleanValue is None:
        raise TwinUnavailable(f"Document field {name!r} is missing or not a boolean.")
    return bool(f.booleanValue)


def _opt_string_field(fields: dict[str, _FirestoreField], name: str) -> str | None:
    f = fields.get(name)
    if f is None:
        return None
    return f.stringValue


def _commit_update_time(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TwinUnavailable("Commit response was not JSON.") from exc
    results = payload.get("writeResults", []) if isinstance(payload, dict) else []
    if results and isinstance(results[0], dict):
        stamp = results[0].get("updateTime")
        if isinstance(stamp, str) and stamp:
            return stamp
    raise TwinUnavailable("Commit response has no update time.")


def _parse_inventory_doc(doc: _FirestoreDocument) -> InventoryDocument:
    fields = doc.fields
    return InventoryDocument(
        store_id=_string_field(fields, "store_id"),
        sku=_string_field(fields, "sku"),
        shelf_id=_string_field(fields, "shelf_id"),
        slot_id=_string_field(fields, "slot_id"),
        facings=_int_field(fields, "facings"),
        shelf_quantity=_int_field(fields, "shelf_quantity"),
        backroom_quantity=_int_field(fields, "backroom_quantity"),
        version=_int_field(fields, "version"),
        updated_at=_timestamp(_opt_string_field(fields, "updated_at") or "1970-01-01T00:00:00Z"),
    )


def _parse_store_doc(doc: _FirestoreDocument) -> StoreDocument:
    fields = doc.fields
    return StoreDocument(
        store_id=_string_field(fields, "store_id"),
        version=_string_field(fields, "version"),
        updated_at=_timestamp(_opt_string_field(fields, "updated_at") or "1970-01-01T00:00:00Z"),
    )


# ---------------------------------------------------------------------------
# Live Twin repository protocol and implementation
# ---------------------------------------------------------------------------


class LiveTwinRepository(ABC):
    """Abstract boundary for Live Twin reads and bounded versioned mutations.

    Subclasses may target Firestore, an in-memory fake, or any other store
    as long as they satisfy this interface.
    """

    @abstractmethod
    def get_store(self, store_id: str) -> StoreDocument | None:
        """Return the store document or None if it does not exist."""

    @abstractmethod
    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]:
        """Return all inventory documents for a store."""

    @abstractmethod
    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        """Return one inventory document or None."""

    @abstractmethod
    def upsert_inventory(self, item: InventoryDocument, expected_version: int | None) -> InventoryDocument:
        """Upsert an inventory document with optional optimistic locking.

        Args:
            item: The inventory document to write.
            expected_version: If set, the write fails with TwinConflict when the
                stored version differs. Pass None for unconditional writes.

        Returns:
            The committed inventory document.

        Raises:
            TwinConflict: expected_version was set and mismatched.
            TwinUnavailable: The store is unreachable.
        """

    @abstractmethod
    def seed(self, store_id: str, version: str, items: Sequence[InventorySeed]) -> None:
        """Replace the entire store inventory with the given seed data.

        Resets all SKU documents and the store metadata document.
        Idempotent: safe to call multiple times.
        """

    @abstractmethod
    def reset(self, store_id: str) -> None:
        """Delete all inventory documents for a store.

        The store metadata document is left in place but marked with a new
        version tag so consumers can detect the reset.
        """

    @abstractmethod
    def commit_inventory(
        self, store_id: str, items: Sequence[tuple[InventoryDocument, int]]
    ) -> StoreDocument:
        """Atomically write every item and advance the store ``v<N>`` version.

        Each item is written only if its stored version equals the paired
        expected version. Either every write and the store version change
        land, or none do.

        Raises:
            TwinConflict: An item is missing or at another version, or the store
                changed concurrently. Nothing was written.
            TwinNotFound: The store document does not exist.
            TwinUnavailable: The store is unreachable.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the underlying store is reachable."""


# ---------------------------------------------------------------------------
# Production Firestore REST implementation
# ---------------------------------------------------------------------------


class FirestoreLiveTwinRepository(LiveTwinRepository):
    """Firestore-backed Live Twin repository.

    Uses the Firestore REST API directly (no Google client library).
    Implements bounded versioned mutation via optimistic concurrency control
    (compare-and-swap on the document updateTime read with its version).

    Canonical paths:
        /stores/{store_id}                  – Store metadata
        /stores/{store_id}/inventory/{sku}   – Per-SKU inventory (subcollection)
    """

    def __init__(
        self,
        config: TwinConfig | None = None,
        runner: CommandRunner | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = (config or TwinConfig()).validated()
        self._runner = runner
        self._transport = transport or UrllibTransport()
        self._token: str | None = None
        self._credentials: Any = None
        self._token_lock = threading.Lock()

    # ------------------------------------------------------------------
    # LiveTwinRepository interface
    # ------------------------------------------------------------------

    def get_store(self, store_id: str) -> StoreDocument | None:
        read = self._read_document(_doc_name(self._config, COLLECTION_STORE, store_id), "get_store")
        return _parse_store_doc(read[0]) if read is not None else None

    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]:
        # Use the subcollection path: /stores/{store_id}/inventory
        # This is a real Firestore collection under the store document.
        url = (
            f"{_database_root(self._config.project)}"
            f"/stores/{store_id}/inventory"
        )
        response = self._call("GET", url, None)
        if response.status == 404:
            return []
        if response.status != 200:
            raise _http_error("list_inventory", response.status, response.body)
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise TwinUnavailable("Inventory list response is not JSON.") from exc
        if not isinstance(payload, dict):
            raise TwinUnavailable("Inventory list response is malformed.")
        fields_map = payload.get("fields", {})
        if not isinstance(fields_map, dict):
            return []
        # A collection group response with documents array
        documents = payload.get("documents", [])
        results: list[InventoryDocument] = []
        for doc_data in documents:
            if not isinstance(doc_data, dict):
                continue
            name = doc_data.get("name", "")
            fields = doc_data.get("fields", {})
            if not isinstance(fields, dict):
                continue
            doc = _FirestoreDocument(
                name=name,
                fields={k: _FirestoreField(**v) for k, v in fields.items()},
            )
            try:
                results.append(_parse_inventory_doc(doc))
            except TwinUnavailable:
                continue  # Skip malformed documents
        return results

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        url = _doc_name(self._config, COLLECTION_STORE, store_id, "inventory", sku)
        read = self._read_document(url, "get_inventory")
        return _parse_inventory_doc(read[0]) if read is not None else None

    def upsert_inventory(
        self, item: InventoryDocument, expected_version: int | None
    ) -> InventoryDocument:
        doc_name = _doc_name(self._config, COLLECTION_STORE, item.store_id, "inventory", item.sku)
        write: dict[str, Any] = {
            "update": {"name": doc_name, "fields": _inventory_fields(item, datetime.now(timezone.utc))}
        }
        if expected_version is None:
            # Create only: never overwrite a document whose version was not checked.
            write["currentDocument"] = {"exists": False}
        else:
            # Firestore preconditions are `exists` or `updateTime`; there is no
            # field-value precondition. Read the version with its updateTime and
            # make the write conditional on that updateTime.
            read = self._read_document(doc_name, "get_inventory")
            if read is None:
                write["currentDocument"] = {"exists": False}
            else:
                current = _parse_inventory_doc(read[0])
                if current.version != expected_version:
                    raise TwinConflict(item.sku, current.version, item.version)
                write["currentDocument"] = {"updateTime": read[1]}
        response = self._call("POST", f"{_database_root(self._config.project)}:commit", {"writes": [write]})
        if response.status == 200:
            return item
        if _precondition_conflict(response.status, response.body):
            latest = self.get_inventory(item.store_id, item.sku)
            if latest is not None:
                raise TwinConflict(item.sku, latest.version, item.version)
            raise TwinConflict(item.sku, -1, item.version)
        raise _http_error("upsert_inventory", response.status, response.body)

    def seed(self, store_id: str, version: str, items: Sequence[InventorySeed]) -> None:
        now = datetime.now(timezone.utc)
        writes: list[dict[str, Any]] = []

        # Upsert store metadata
        store_doc = _doc_name(self._config, COLLECTION_STORE, store_id)
        writes.append(
            {
                "update": {
                    "name": store_doc,
                    "fields": {
                        "store_id": {"stringValue": store_id},
                        "version": {"stringValue": version},
                        "updated_at": {"timestampValue": now.isoformat()},
                    },
                }
            }
        )

        # Upsert all seed items as inventory subcollection documents.
        for seed in items:
            inv_doc = _doc_name(self._config, COLLECTION_STORE, store_id, "inventory", seed.sku)
            writes.append(
                {
                    "update": {
                        "name": inv_doc,
                        "fields": {
                            "store_id": {"stringValue": store_id},
                            "sku": {"stringValue": seed.sku},
                            "shelf_id": {"stringValue": seed.shelf_id},
                            "slot_id": {"stringValue": seed.slot_id},
                            "facings": {"integerValue": str(seed.facings)},
                            "shelf_quantity": {"integerValue": str(seed.shelf_quantity)},
                            "backroom_quantity": {"integerValue": str(seed.backroom_quantity)},
                            "version": {"integerValue": "1"},
                            "updated_at": {"timestampValue": now.isoformat()},
                        },
                    }
                }
            )

        payload: dict[str, Any] = {"writes": writes}
        response = self._call(
            "POST", f"{_database_root(self._config.project)}:commit", payload
        )
        if response.status != 200:
            raise _http_error("seed", response.status, response.body)

    def reset(self, store_id: str) -> None:
        # List all inventory documents and delete them
        items = self.list_inventory(store_id)
        if not items:
            return
        writes: list[dict[str, Any]] = []
        for item in items:
            doc_name = _doc_name(self._config, COLLECTION_STORE, store_id, "inventory", item.sku)
            writes.append(
                {
                    "delete": doc_name,
                }
            )
        # Bump the store version to signal a reset
        store_doc = _doc_name(self._config, COLLECTION_STORE, store_id)
        current = self.get_store(store_id)
        new_version = _bump_version(current.version) if current else "v1"
        now = datetime.now(timezone.utc)
        writes.append(
            {
                "update": {
                    "name": store_doc,
                    "fields": {
                        "store_id": {"stringValue": store_id},
                        "version": {"stringValue": new_version},
                        "updated_at": {"timestampValue": now.isoformat()},
                    },
                }
            }
        )
        payload: dict[str, Any] = {"writes": writes}
        response = self._call(
            "POST", f"{_database_root(self._config.project)}:commit", payload
        )
        if response.status != 200:
            raise _http_error("reset", response.status, response.body)

    def commit_inventory(
        self, store_id: str, items: Sequence[tuple[InventoryDocument, int]]
    ) -> StoreDocument:
        # One :commit is atomic in Firestore. Each document is guarded by the
        # updateTime read together with its version, so a write that lands
        # after the read fails the whole commit with FAILED_PRECONDITION.
        store_url = _doc_name(self._config, COLLECTION_STORE, store_id)
        store_read = self._read_document(store_url, "get_store")
        if store_read is None:
            raise TwinNotFound(_doc_path(COLLECTION_STORE, store_id))
        current_store = _parse_store_doc(store_read[0])
        now = datetime.now(timezone.utc)
        writes: list[dict[str, Any]] = []
        for item, expected_version in items:
            url = _doc_name(self._config, COLLECTION_STORE, store_id, "inventory", item.sku)
            read = self._read_document(url, "get_inventory")
            if read is None:
                raise TwinConflict(item.sku, -1, item.version)
            current = _parse_inventory_doc(read[0])
            if current.version != expected_version:
                raise TwinConflict(item.sku, current.version, item.version)
            writes.append(
                {
                    "update": {"name": url, "fields": _inventory_fields(item, now)},
                    "currentDocument": {"updateTime": read[1]},
                }
            )
        bumped = StoreDocument(store_id=store_id, version=_bump_version(current_store.version), updated_at=now)
        writes.append(
            {
                "update": {
                    "name": store_url,
                    "fields": {
                        "store_id": {"stringValue": store_id},
                        "version": {"stringValue": bumped.version},
                        "updated_at": {"timestampValue": now.isoformat()},
                    },
                },
                "currentDocument": {"updateTime": store_read[1]},
            }
        )
        response = self._call("POST", f"{_database_root(self._config.project)}:commit", {"writes": writes})
        if response.status == 200:
            return bumped
        if _precondition_conflict(response.status, response.body):
            for item, expected_version in items:
                latest = self.get_inventory(store_id, item.sku)
                if latest is None or latest.version != expected_version:
                    raise TwinConflict(item.sku, latest.version if latest else -1, item.version)
            raise TwinConflict(store_id, -1, -1)
        raise _http_error("commit_inventory", response.status, response.body)

    def is_available(self) -> bool:
        url = f"{_database_root(self._config.project)}/stores"
        try:
            response = self._call("GET", url, None)
            return response.status in (200, 404)
        except TwinUnavailable:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(
        self, method: str, url: str, payload: dict[str, Any] | None
    ) -> HttpResponse:
        raw = None if payload is None else json.dumps(payload).encode("utf-8")
        try:
            return self._transport.request(method, url, raw, self._headers())
        except TwinUnavailable:
            raise
        except Exception as exc:
            raise TwinUnavailable(f"Firestore request failed: {exc}") from exc

    def _read_document(self, url: str, action: str) -> tuple[_FirestoreDocument, str] | None:
        """GET one document. Returns it with its server ``updateTime``, or None when missing."""
        response = self._call("GET", url, None)
        if response.status == 404:
            return None
        if response.status != 200:
            raise _http_error(action, response.status, response.body)
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise TwinUnavailable("Firestore document response is not JSON.") from exc
        if not isinstance(payload, dict):
            raise TwinUnavailable("Firestore document response is malformed.")
        fields = payload.get("fields", {})
        if not isinstance(fields, dict):
            raise TwinUnavailable("Firestore document has no fields.")
        doc = _FirestoreDocument(
            name=payload.get("name", ""), fields={k: _FirestoreField(**v) for k, v in fields.items()}
        )
        return doc, str(payload.get("updateTime", ""))

    def _headers(self) -> dict[str, str]:
        token = self._get_token()
        if not token or any(c in token for c in "\n\r\t "):
            raise TwinUnavailable("Could not read an access token.")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _get_token(self) -> str:
        """Access token from Application Default Credentials (the Cloud Run service identity).

        Credentials are refreshed when they expire. An injected ``runner`` keeps the
        local ``gcloud`` path for tooling; the service never needs a ``gcloud`` executable.
        """
        with self._token_lock:
            if self._runner is not None:
                if self._token is None:
                    self._token = self._runner.run(["gcloud", "auth", "print-access-token", "--quiet"]).strip()
                return self._token
            try:
                if self._credentials is None:
                    import google.auth

                    self._credentials, _ = google.auth.default(scopes=[FIRESTORE_SCOPE])
                if not self._credentials.valid:
                    self._credentials.refresh(_UrllibAuthRequest())
                token = self._credentials.token
            except Exception as exc:
                raise TwinUnavailable(
                    f"Application Default Credentials are not available: {type(exc).__name__}"
                ) from None
            return str(token or "")


class _UrllibAuthResponse:
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
        request = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(request, timeout=timeout or 10) as response:
                return _UrllibAuthResponse(response.status, dict(response.headers), response.read())
        except urllib.error.HTTPError as exc:
            return _UrllibAuthResponse(exc.code, dict(exc.headers or {}), exc.read())


def _inventory_fields(item: InventoryDocument, now: datetime) -> dict[str, Any]:
    return {
        "store_id": {"stringValue": item.store_id},
        "sku": {"stringValue": item.sku},
        "shelf_id": {"stringValue": item.shelf_id},
        "slot_id": {"stringValue": item.slot_id},
        "facings": {"integerValue": str(item.facings)},
        "shelf_quantity": {"integerValue": str(item.shelf_quantity)},
        "backroom_quantity": {"integerValue": str(item.backroom_quantity)},
        "version": {"integerValue": str(item.version)},
        "updated_at": {"timestampValue": now.isoformat()},
    }


def _bump_version(version: str) -> str:
    """Increment a 'v<N>' version string."""
    if version.startswith("v"):
        try:
            n = int(version[1:])
            return f"v{n + 1}"
        except ValueError:
            return "v2"
    return "v2"


class CommandRunner(Protocol):
    """Protocol for executing shell commands (for token acquisition)."""

    def run(self, args: list[str]) -> str: ...


# ---------------------------------------------------------------------------
# In-memory fake (isolated development fixtures)
# ---------------------------------------------------------------------------


class InMemoryTwinRepository(LiveTwinRepository):
    """In-process fake for isolated testing without Firestore.

    Thread-safe, deterministic, no network calls.
    Satisfies the LiveTwinRepository interface.
    """

    def __init__(self) -> None:
        self._stores: dict[str, StoreDocument] = {}
        self._inventory: dict[str, dict[str, InventoryDocument]] = {}  # store_id → sku → doc
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # LiveTwinRepository interface
    # ------------------------------------------------------------------

    def get_store(self, store_id: str) -> StoreDocument | None:
        with self._lock:
            return self._stores.get(store_id)

    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]:
        with self._lock:
            return list(self._inventory.get(store_id, {}).values())

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        with self._lock:
            return self._inventory.get(store_id, {}).get(sku)

    def upsert_inventory(
        self, item: InventoryDocument, expected_version: int | None
    ) -> InventoryDocument:
        with self._lock:
            store = self._inventory.setdefault(item.store_id, {})
            existing = store.get(item.sku)
            if expected_version is not None:
                if existing is not None and existing.version != expected_version:
                    raise TwinConflict(item.sku, existing.version, item.version)
                # If existing is None and expected_version is set, that's fine (create).
                # If existing.version == expected_version, that's also fine (update).
            doc = InventoryDocument(
                store_id=item.store_id,
                sku=item.sku,
                shelf_id=item.shelf_id,
                slot_id=item.slot_id,
                facings=item.facings,
                shelf_quantity=item.shelf_quantity,
                backroom_quantity=item.backroom_quantity,
                version=item.version,
                updated_at=datetime.now(timezone.utc),
            )
            store[item.sku] = doc
            return doc

    def seed(self, store_id: str, version: str, items: Sequence[InventorySeed]) -> None:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._stores[store_id] = StoreDocument(
                store_id=store_id,
                version=version,
                updated_at=now,
            )
            self._inventory[store_id] = {}
            for seed in items:
                self._inventory[store_id][seed.sku] = InventoryDocument(
                    store_id=store_id,
                    sku=seed.sku,
                    shelf_id=seed.shelf_id,
                    slot_id=seed.slot_id,
                    facings=seed.facings,
                    shelf_quantity=seed.shelf_quantity,
                    backroom_quantity=seed.backroom_quantity,
                    version=1,
                    updated_at=now,
                )

    def reset(self, store_id: str) -> None:
        with self._lock:
            if store_id in self._inventory:
                self._inventory[store_id] = {}
            current = self._stores.get(store_id)
            new_version = _bump_version(current.version) if current else "v1"
            self._stores[store_id] = StoreDocument(
                store_id=store_id,
                version=new_version,
                updated_at=datetime.now(timezone.utc),
            )

    def commit_inventory(
        self, store_id: str, items: Sequence[tuple[InventoryDocument, int]]
    ) -> StoreDocument:
        with self._lock:
            current = self._stores.get(store_id)
            if current is None:
                raise TwinNotFound(f"stores/{store_id}")
            stored = self._inventory.setdefault(store_id, {})
            for item, expected_version in items:
                existing = stored.get(item.sku)
                if existing is None or existing.version != expected_version:
                    raise TwinConflict(item.sku, existing.version if existing else -1, item.version)
            now = datetime.now(timezone.utc)
            for item, _expected in items:
                stored[item.sku] = item.model_copy(update={"updated_at": now})
            bumped = StoreDocument(store_id=store_id, version=_bump_version(current.version), updated_at=now)
            self._stores[store_id] = bumped
            return bumped

    def is_available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# StoreRepository adapter (preserves the existing interface for routes.py)
# ---------------------------------------------------------------------------


class StoreRepository:
    """Adapter that wraps a LiveTwinRepository and exposes the same interface
    as the existing fixture-based StoreRepository.

    This allows routes.py to keep working unchanged while the underlying store
    is backed by Firestore.
    """

    def __init__(
        self,
        live_twin: LiveTwinRepository,
        store_id: str,
    ) -> None:
        self._twin = live_twin
        self._store_id = store_id
        self._loaded = False
        self.error: str | None = None
        self._version: int = 0
        self._check()

    def _check(self) -> None:
        try:
            store_doc = self._twin.get_store(self._store_id)
            if store_doc is None:
                self.error = "Store not found in Firestore."
                self._loaded = False
                return
            self._version = self._parse_version(store_doc.version)
            self._loaded = True
            self.error = None
        except TwinUnavailable as exc:
            self.error = str(exc)
            self._loaded = False

    @staticmethod
    def _parse_version(version: str) -> int:
        if version.startswith("v"):
            try:
                return int(version[1:])
            except ValueError:
                return 0
        return 0

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def store_id(self) -> str:
        return self._store_id

    def view(self) -> dict[str, Any]:
        """Return a dict matching StoreResponse for the HTTP route."""
        store_doc = self._twin.get_store(self._store_id)
        if store_doc is None:
            raise RuntimeError("Store is not loaded")
        items = self._twin.list_inventory(self._store_id)
        return {
            "store_id": store_doc.store_id,
            "context_version": f"{store_doc.store_id}:{store_doc.version}",
            "version": store_doc.version,
            "products": [item.to_product_inventory() for item in items],
        }

    def inventory(self, sku: str) -> dict[str, Any] | None:
        """Return a dict matching ProductInventory or None."""
        doc = self._twin.get_inventory(self._store_id, sku)
        if doc is None:
            return None
        return doc.to_product_inventory()
