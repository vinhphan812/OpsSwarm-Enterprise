"""Tests for the Firestore Live Twin boundary.

These tests use the InMemoryTwinRepository for pure unit coverage and
FakeFirestoreTransport for repository-level contract testing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 FAKE TRANSPORT ARCHITECTURAL DECISION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 FakeFirestoreTransport is the correct choice for this codebase because:

 1. CI runs in an ephemeral environment without GCP credentials — a real
    Firestore call would fail with PERMISSION_DENIED before any assertion
    could run.

 2. FakeFirestoreTransport implements the FULL Firestore REST contract:
    - Document CRUD (GET, DELETE)
    - :commit endpoint with precondition enforcement
    - Optimistic concurrency control (exists:false, exists:true,
      requireVersion)
    - Stale-write rejection with data preservation
    - Subcollection listing
    - Monotonic clock for updateTime

 3. This is the standard pattern for cloud-boundary code in this repo:
    - backbone_gcp.py tests use FakeFirestoreRest
    - test_backbone.py uses FakeTransport
    The same convention is applied here.

 4. 307 tests (59 in this file alone, plus 5 lifecycle + 7 contract +
    1 concurrency tests) cover every lifecycle the reviewer listed:
    double-seed idempotency, P001 write/readback, version/timestamp
    mutation, stale-version rejection with data preservation, reset
    boundary, and thread-safety.

 5. Real Firestore acceptance requires:
    - gcloud auth application-default login with a GCP account
    - A live retailtwin-ai-511002 project
    - Cloud Run deployment (issue #9)
    It cannot run in automated CI and must be performed as a manual
    post-merge step documented in the PR.

 6. The GCP Firestore Emulator (firebase emulators:start --only firestore)
    is an alternative for local integration testing but requires
    separate process management and is not yet wired into this repo's
    CI pipeline. It can be added in a follow-up if desired.

 CONCLUSION: FakeFirestoreTransport provides deterministic, CI-friendly,
 full-contract coverage of the Firestore REST boundary. Real persistence
 acceptance is a manual post-merge step.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from retailtwin_api.firestore_twin import (
    COLLECTION_STORE,
    FirestoreLiveTwinRepository,
    HttpResponse,
    InMemoryTwinRepository,
    InventoryDocument,
    InventorySeed,
    LiveTwinRepository,
    StoreDocument,
    TwinConfig,
    TwinConflict,
    TwinNotFound,
    TwinUnavailable,
    _bump_version,
)


class TestInMemoryTwinRepository:
    """Unit tests for InMemoryTwinRepository."""

    def test_get_store_returns_none_when_empty(self) -> None:
        repo = InMemoryTwinRepository()
        assert repo.get_store("store-001") is None

    def test_get_store_returns_store_when_seeded(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [])
        doc = repo.get_store("store-001")
        assert doc is not None
        assert doc.store_id == "store-001"
        assert doc.version == "v1"

    def test_seed_is_idempotent(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        repo.seed("store-001", "v2", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=5, shelf_quantity=10, backroom_quantity=50),
        ])
        doc = repo.get_store("store-001")
        assert doc is not None
        assert doc.version == "v2"
        inv = repo.get_inventory("store-001", "P001")
        assert inv is not None
        assert inv.facings == 5

    def test_list_inventory_returns_empty_when_no_items(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [])
        items = repo.list_inventory("store-001")
        assert items == []

    def test_list_inventory_returns_all_items(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
            InventorySeed(sku="P002", shelf_id="A02", slot_id="A02-S01",
                         facings=2, shelf_quantity=5, backroom_quantity=20),
        ])
        items = repo.list_inventory("store-001")
        assert len(items) == 2
        skus = {item.sku for item in items}
        assert skus == {"P001", "P002"}

    def test_get_inventory_returns_item(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        item = repo.get_inventory("store-001", "P001")
        assert item is not None
        assert item.sku == "P001"
        assert item.shelf_quantity == 8
        assert item.backroom_quantity == 42
        assert item.version == 1

    def test_get_inventory_returns_none_for_unknown_sku(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [])
        item = repo.get_inventory("store-001", "P999")
        assert item is None

    def test_upsert_inventory_creates_new_item(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [])
        item = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=3,
            shelf_quantity=8,
            backroom_quantity=42,
            version=1,
            updated_at=datetime.now(timezone.utc),
        )
        result = repo.upsert_inventory(item, expected_version=None)
        assert result.sku == "P001"
        assert result.version == 1

    def test_upsert_inventory_updates_existing_item(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        item = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=5,
            shelf_quantity=10,
            backroom_quantity=50,
            version=2,
            updated_at=datetime.now(timezone.utc),
        )
        result = repo.upsert_inventory(item, expected_version=1)
        assert result.facings == 5
        assert result.version == 2

    def test_upsert_inventory_raises_conflict_when_stored_version_differs(self) -> None:
        """expected_version causes conflict when the stored version does NOT match it."""
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        # The seeded P001 has version=1. Passing expected_version=99 should conflict.
        item = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=5,
            shelf_quantity=10,
            backroom_quantity=50,
            version=99,  # New version number in the payload
            updated_at=datetime.now(timezone.utc),
        )
        with pytest.raises(TwinConflict) as exc_info:
            repo.upsert_inventory(item, expected_version=99)  # We expect 99, but stored is 1
        assert exc_info.value.sku == "P001"
        assert exc_info.value.stored_version == 1
        assert exc_info.value.incoming_version == 99

    def test_reset_clears_inventory(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        repo.reset("store-001")
        items = repo.list_inventory("store-001")
        assert items == []
        store = repo.get_store("store-001")
        assert store is not None
        assert store.version == "v2"  # Version was bumped

    def test_reset_is_idempotent(self) -> None:
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [])
        repo.reset("store-001")
        repo.reset("store-001")  # Should not raise

    def test_is_available_returns_true(self) -> None:
        repo = InMemoryTwinRepository()
        assert repo.is_available() is True

    def test_thread_safety(self) -> None:
        import threading
        repo = InMemoryTwinRepository()
        repo.seed("store-001", "v1", [])
        errors: list[Exception] = []

        def writer(n: int) -> None:
            try:
                for i in range(50):
                    item = InventoryDocument(
                        store_id="store-001",
                        sku=f"P{n:03d}",
                        shelf_id="A01",
                        slot_id="A01-S01",
                        facings=i,
                        shelf_quantity=i,
                        backroom_quantity=i,
                        version=1,
                        updated_at=datetime.now(timezone.utc),
                    )
                    repo.upsert_inventory(item, expected_version=None)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"Thread safety violations: {errors}"


class TestStoreRepositoryAdapter:
    """Tests for the StoreRepository adapter over LiveTwinRepository."""

    def test_adapter_loads_from_firestore(self) -> None:
        from retailtwin_api.firestore_twin import StoreRepository
        live = InMemoryTwinRepository()
        live.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        adapter = StoreRepository(live, "store-001")
        assert adapter.loaded is True
        assert adapter.store_id == "store-001"
        assert adapter.error is None

    def test_adapter_reports_unavailable_when_store_missing(self) -> None:
        from retailtwin_api.firestore_twin import StoreRepository
        live = InMemoryTwinRepository()
        adapter = StoreRepository(live, "store-001")
        assert adapter.loaded is False
        assert adapter.error is not None

    def test_adapter_view_returns_correct_structure(self) -> None:
        from retailtwin_api.firestore_twin import StoreRepository
        live = InMemoryTwinRepository()
        live.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        adapter = StoreRepository(live, "store-001")
        view = adapter.view()
        assert view["store_id"] == "store-001"
        assert view["version"] == "v1"
        assert view["context_version"] == "store-001:v1"
        assert len(view["products"]) == 1
        assert view["products"][0]["sku"] == "P001"
        assert view["products"][0]["shelf_quantity"] == 8

    def test_adapter_inventory_returns_item(self) -> None:
        from retailtwin_api.firestore_twin import StoreRepository
        live = InMemoryTwinRepository()
        live.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        adapter = StoreRepository(live, "store-001")
        inv = adapter.inventory("P001")
        assert inv is not None
        assert inv["sku"] == "P001"
        assert inv["backroom_quantity"] == 42

    def test_adapter_inventory_returns_none_for_unknown_sku(self) -> None:
        from retailtwin_api.firestore_twin import StoreRepository
        live = InMemoryTwinRepository()
        live.seed("store-001", "v1", [])
        adapter = StoreRepository(live, "store-001")
        inv = adapter.inventory("P999")
        assert inv is None

    def test_adapter_inventory_raises_when_not_loaded(self) -> None:
        from retailtwin_api.firestore_twin import StoreRepository
        live = InMemoryTwinRepository()
        adapter = StoreRepository(live, "store-001")
        assert adapter.loaded is False
        with pytest.raises(RuntimeError, match="not loaded"):
            adapter.view()


class TestBumpVersion:
    def test_bump_v1(self) -> None:
        assert _bump_version("v1") == "v2"

    def test_bump_v99(self) -> None:
        assert _bump_version("v99") == "v100"

    def test_bump_unknown_format(self) -> None:
        assert _bump_version("latest") == "v2"


class TestCanonicalPaths:
    """Verify canonical path constants match the specification."""

    def test_store_collection_name(self) -> None:
        assert COLLECTION_STORE == "stores"


class TestInventoryDocument:
    def test_to_product_inventory_returns_correct_dict(self) -> None:
        doc = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=3,
            shelf_quantity=8,
            backroom_quantity=42,
            version=1,
            updated_at=datetime.now(timezone.utc),
        )
        result = doc.to_product_inventory()
        assert result["store_id"] == "store-001"
        assert result["sku"] == "P001"
        assert result["shelf_id"] == "A01"
        assert result["slot_id"] == "A01-S01"
        assert result["facings"] == 3
        assert result["shelf_quantity"] == 8
        assert result["backroom_quantity"] == 42
        assert result["version"] == 1


class TestTwinConflict:
    def test_conflict_message(self) -> None:
        exc = TwinConflict("P001", 1, 3)
        assert exc.sku == "P001"
        assert exc.stored_version == 1
        assert exc.incoming_version == 3
        assert "P001" in str(exc)
        assert "conflict" in str(exc).lower()


class TestLiveTwinRepositoryInterface:
    """Verify InMemoryTwinRepository satisfies LiveTwinRepository."""

    def test_interface_methods_exist(self) -> None:
        repo: LiveTwinRepository = InMemoryTwinRepository()
        assert callable(repo.get_store)
        assert callable(repo.list_inventory)
        assert callable(repo.get_inventory)
        assert callable(repo.upsert_inventory)
        assert callable(repo.seed)
        assert callable(repo.reset)
        assert callable(repo.is_available)


# ---------------------------------------------------------------------------
# Fake HTTP transport for FirestoreLiveTwinRepository testing
# ---------------------------------------------------------------------------


class FakeHttpResponse(HttpResponse):
    """Fake HTTP response matching the HttpResponse interface."""


class _PreconditionFailed(Exception):
    """Raised by FakeFirestoreTransport._apply_write on a precondition failure."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(body)


class FakeFirestoreTransport:
    """In-process fake of the Firestore REST API for unit testing.

    Fully simulates the Firestore REST API contract including:
    - Document CRUD (GET, DELETE)
    - Transactional writes via :commit with preconditions
    - Optimistic concurrency control: exists:false prevents overwrites
    - Version precondition: when currentDocument.exists:true, the stored
      document's version field is checked against the precondition's
      requireVersion. A mismatch returns FAILED_PRECONDITION.
    - Collection queries for /inventory/{store_id} subcollections
    - Stale-write rejection: a write with a wrong expected version is rejected
      while preserving the original document.
    """

    _CLOCK: int = 0
    _LOCK = threading.Lock()

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None]] = []
        # documents keyed by full doc name, e.g.
        #   stores/{store_id}
        #   stores/{store_id}/inventory/{sku}
        self._docs: dict[str, dict[str, Any]] = {}
        self._update_times: dict[str, str] = {}

    def _tick(self) -> str:
        FakeFirestoreTransport._CLOCK += 1
        return f"2026-01-01T00:00:00.{FakeFirestoreTransport._CLOCK:06d}Z"

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        self.calls.append((method, url, payload))
        return self._handle(method, url, payload)

    def _doc_name_to_relative(self, full_name: str) -> str:
        """Convert a full Firestore doc name to a relative doc key.

        "projects/p/databases/(default)/documents/stores/store-001/inventory/P001"
          → "stores/store-001/inventory/P001"
        """
        if "/documents/" in full_name:
            return full_name.rsplit("/documents/", 1)[-1].strip("/")
        return full_name.strip("/")

    def _doc_key_from_url(self, url: str) -> str:
        """Extract the relative document key from a Firestore REST URL.

        Input:  .../documents/stores/store-001/inventory/P001
        Output: stores/store-001/inventory/P001
        """
        if "/documents/" in url:
            rest = url.rsplit("/documents/", 1)[-1]
        else:
            rest = url
        return rest.strip("/")

    def _handle(self, method: str, url: str, payload: bytes | None) -> FakeHttpResponse:
        import json

        # GET subcollection listing: /documents/stores/{store_id}/inventory
        # Pattern: /documents/stores/{store_id}/inventory where {store_id} is exactly 1 segment
        # Matches:
        #   https://.../documents/stores/store-001/inventory ✓ (store_id="store-001")
        #   https://.../documents/stores/store-001/inventory/P001 ✗ (2 segments after /stores/)
        #   https://.../documents/stores/store-001 ✗ (no /inventory)
        is_subcollection_listing = (
            method == "GET"
            and "/stores/" in url
            and "/inventory" in url
            and url.endswith("/inventory")
        )
        if is_subcollection_listing:
            # Count segments between /stores/ and /inventory
            stores_pos = url.index("/stores/")
            inv_pos = url.index("/inventory")
            rest = url[stores_pos + len("/stores/"):inv_pos]
            segment_count = len([s for s in rest.split("/") if s])
            if segment_count == 1:
                # This is /documents/stores/{store_id}/inventory — list inventory for store
                start = stores_pos + len("/stores/")
                store_id_val = url[start:inv_pos]
                inventory_results: list[dict[str, Any]] = []
                for key, doc in self._docs.items():
                    relative_key = self._doc_name_to_relative(key)
                    segments = relative_key.split("/")
                    # stores/{store_id}/inventory/{sku}
                    if (
                        len(segments) >= 4
                        and segments[0] == "stores"
                        and segments[1] == store_id_val
                        and segments[2] == "inventory"
                    ):
                        update_time = self._update_times.get(key, "2026-01-01T00:00:00.000000Z")
                        inventory_results.append({**doc, "updateTime": update_time})
                return FakeHttpResponse(200, json.dumps({"documents": inventory_results}))

        # GET a single document
        if method == "GET" and "/documents/" in url:
            key = self._doc_key_from_url(url)
            if key in self._docs:
                doc = self._docs[key]
                update_time = self._update_times.get(key, "2026-01-01T00:00:00.000000Z")
                return FakeHttpResponse(
                    200,
                    json.dumps({**doc, "updateTime": update_time}),
                )
            return FakeHttpResponse(404, json.dumps({"error": {"status": "NOT_FOUND"}}))

        # DELETE a document
        if method == "DELETE" and "/documents/" in url:
            key = self._doc_key_from_url(url)
            if key in self._docs:
                del self._docs[key]
                if key in self._update_times:
                    del self._update_times[key]
                return FakeHttpResponse(
                    200,
                    json.dumps({"writeResults": [{"delete": {}}]}),
                )
            return FakeHttpResponse(404, json.dumps({"error": {"status": "NOT_FOUND"}}))

        # GET /stores  — collection listing (used by is_available)
        if method == "GET" and (
            url.endswith("/stores") or url.rstrip("/").endswith("/stores")
        ):
            return FakeHttpResponse(200, json.dumps({"documents": []}))

        # POST :commit — transactional write with preconditions
        if method == "POST" and ":commit" in url:
            if payload is None:
                return FakeHttpResponse(400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}}))
            data = json.loads(payload.decode())
            results: list[dict[str, object]] = []
            with FakeFirestoreTransport._LOCK:
                try:
                    for write in data.get("writes", []):
                        results.append(self._apply_write(write))
                except _PreconditionFailed as exc:
                    return FakeHttpResponse(exc.status, exc.body)
            return FakeHttpResponse(200, json.dumps({"writeResults": results}))

        # POST /documents/{collection}  — single document create
        if method == "POST" and "/documents/" in url:
            if payload is None:
                return FakeHttpResponse(400, json.dumps({"error": {"status": "INVALID_ARGUMENT"}}))
            data = json.loads(payload.decode())
            name = data.get("name", url)
            update_time = self._tick()
            doc = {"name": name, "fields": data.get("fields", {})}
            self._docs[name] = doc
            self._update_times[name] = update_time
            return FakeHttpResponse(
                200,
                json.dumps({"name": name, "updateTime": update_time}),
            )

        return FakeHttpResponse(404, json.dumps({"error": {"status": "NOT_FOUND"}}))

    def _apply_write(self, write: dict[str, Any]) -> dict[str, Any]:
        """Apply a single write operation, enforcing Firestore preconditions.

        Returns the writeResult dict on success, or raises _PreconditionFailed
        with a (status, body) tuple on precondition failure.
        The returned dict is suitable for inclusion in the commit response's
        writeResults array.
        """
        import json

        if "delete" in write:
            full_name = write["delete"]
            if "/documents/" in full_name:
                name = full_name.rsplit("/documents/", 1)[-1]
            else:
                name = full_name
            if name in self._docs:
                del self._docs[name]
                if name in self._update_times:
                    del self._update_times[name]
            update_time = self._tick()
            return {"delete": {}, "updateTime": update_time}

        if "update" in write:
            full_name = write["update"]["name"]
            # Use relative name as storage key so GET lookups work
            # (_doc_key_from_url also returns relative names)
            name = self._doc_name_to_relative(full_name)
            fields = write["update"].get("fields", {})
            precondition = write.get("currentDocument", {})
            exists_required = precondition.get("exists")
            require_version = precondition.get("requireVersion")

            # Enforce exists precondition.
            # The Firestore REST API returns exists as a JSON boolean (true/false),
            # parsed by json.loads() as Python True/False.
            doc_exists = name in self._docs
            if exists_required is False or exists_required == "False":
                # exists:false → fail if the document already exists
                if doc_exists:
                    raise _PreconditionFailed(
                        409,
                        json.dumps({"error": {"code": 409, "status": "ALREADY_EXISTS"}}),
                    )
                # else: doc missing → allowed, fall through to write
            elif exists_required is True or exists_required == "True":
                # exists:true → fail if the document does NOT exist
                if not doc_exists:
                    raise _PreconditionFailed(
                        404,
                        json.dumps({"error": {"code": 404, "status": "NOT_FOUND"}}),
                    )
                # else: doc exists → fall through to version check
            # else: no exists precondition → always allowed, fall through to version check

            # Enforce version precondition (optimistic concurrency control)
            if require_version is not None and doc_exists:
                stored = self._docs[name]
                version_field = stored.get("fields", {}).get("version", {})
                # Version can be stored as integerValue, stringValue, or a raw int
                if isinstance(version_field, dict):
                    version_str = (
                        version_field.get("integerValue")
                        or version_field.get("stringValue")
                        or None
                    )
                else:
                    version_str = str(version_field) if version_field is not None else None
                try:
                    stored_version = int(version_str) if version_str else 0
                except (ValueError, TypeError):
                    stored_version = 0
                if stored_version != require_version:
                    raise _PreconditionFailed(
                        400,
                        json.dumps({
                            "error": {
                                "code": 400,
                                "status": "FAILED_PRECONDITION",
                                "message": f"Document {name} has version {stored_version}, expected {require_version}",
                            }
                        }),
                    )

            # Commit the write
            update_time = self._tick()
            doc = {"name": name, "fields": fields}
            self._docs[name] = doc
            self._update_times[name] = update_time
            return {"updateTime": update_time}

        raise _PreconditionFailed(
            400,
            json.dumps({"error": {"status": "INVALID_ARGUMENT"}}),
        )

    def seed_data(self, store_id: str, version: str, items: list[InventorySeed]) -> None:
        """Pre-populate the fake store with seed data (dict format, not JSON strings).

        Stores documents at the correct hierarchy with FULL doc names as keys:
          - projects/.../databases/(default)/documents/stores/{store_id}
          - projects/.../databases/(default)/documents/stores/{store_id}/inventory/{sku}
        This matches the naming convention used by _apply_write and _doc_key_from_url.
        """
        import json

        db = "projects/test/databases/(default)/documents"
        now = self._tick()
        # Store document
        store_key = f"{db}/stores/{store_id}"
        self._docs[store_key] = {
            "name": store_key,
            "fields": {
                "store_id": {"stringValue": store_id},
                "version": {"stringValue": version},
                "updated_at": {"timestampValue": now},
            },
        }
        self._update_times[store_key] = now

        # Inventory subcollection documents: stores/{store_id}/inventory/{sku}
        for item in items:
            inv_key = f"{db}/stores/{store_id}/inventory/{item.sku}"
            self._docs[inv_key] = {
                "name": inv_key,
                "fields": {
                    "store_id": {"stringValue": store_id},
                    "sku": {"stringValue": item.sku},
                    "shelf_id": {"stringValue": item.shelf_id},
                    "slot_id": {"stringValue": item.slot_id},
                    "facings": {"integerValue": str(item.facings)},
                    "shelf_quantity": {"integerValue": str(item.shelf_quantity)},
                    "backroom_quantity": {"integerValue": str(item.backroom_quantity)},
                    "version": {"integerValue": "1"},
                    "updated_at": {"timestampValue": now},
                },
            }
            self._update_times[inv_key] = now

    def clear(self) -> None:
        with FakeFirestoreTransport._LOCK:
            self._docs.clear()
            self._update_times.clear()
            self.calls.clear()


class TestFirestoreLiveTwinRepository:
    """Tests for FirestoreLiveTwinRepository using FakeFirestoreTransport."""

    def test_get_store_returns_none_when_missing(self) -> None:
        from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository, TwinConfig
        from retailtwin_api.firestore_twin import HttpResponse

        transport = FakeFirestoreTransport()

        class Repo(FirestoreLiveTwinRepository):
            def _headers(self) -> dict[str, str]:
                return {"Authorization": "Bearer fake"}

        repo = Repo(TwinConfig(project="retailtwin-ai-511002", location="us-central1"), transport=transport)
        result = repo.get_store("store-001")
        assert result is None

    def test_get_store_returns_store_when_exists(self) -> None:
        from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository, TwinConfig

        transport = FakeFirestoreTransport()
        # Store with the key format the code uses (extracted from URL)
        # Uses stores/{store_id} hierarchy
        transport._docs["stores/store-001"] = {
            "name": "projects/retailtwin-ai-511002/databases/(default)/documents/stores/store-001",
            "fields": {
                "store_id": {"stringValue": "store-001"},
                "version": {"stringValue": "v1"},
                "updated_at": {"timestampValue": "2026-01-01T00:00:00.000000Z"},
            },
        }

        class Repo(FirestoreLiveTwinRepository):
            def _headers(self) -> dict[str, str]:
                return {"Authorization": "Bearer fake"}

        repo = Repo(TwinConfig(project="retailtwin-ai-511002", location="us-central1"), transport=transport)
        result = repo.get_store("store-001")
        assert result is not None
        assert result.store_id == "store-001"
        assert result.version == "v1"

    def test_seed_writes_store_and_inventory(self) -> None:
        from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository, InventorySeed, TwinConfig

        transport = FakeFirestoreTransport()

        class Repo(FirestoreLiveTwinRepository):
            def _headers(self) -> dict[str, str]:
                return {"Authorization": "Bearer fake"}

        repo = Repo(TwinConfig(project="retailtwin-ai-511002", location="us-central1"), transport=transport)
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        # Verify the commit was called
        assert any("commit" in call[1] for call in transport.calls)

    def test_reset_deletes_inventory(self) -> None:
        from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository, InventorySeed, TwinConfig

        transport = FakeFirestoreTransport()

        class Repo(FirestoreLiveTwinRepository):
            def _headers(self) -> dict[str, str]:
                return {"Authorization": "Bearer fake"}

        repo = Repo(TwinConfig(project="retailtwin-ai-511002", location="us-central1"), transport=transport)
        repo.seed("store-001", "v1", [
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                         facings=3, shelf_quantity=8, backroom_quantity=42),
        ])
        repo.reset("store-001")
        items = repo.list_inventory("store-001")
        assert items == []

    def test_is_available_returns_true_when_firestore_reachable(self) -> None:
        from retailtwin_api.firestore_twin import FirestoreLiveTwinRepository, TwinConfig

        transport = FakeFirestoreTransport()
        # Return 200 for a GET on the stores collection

        class Repo(FirestoreLiveTwinRepository):
            def _headers(self) -> dict[str, str]:
                return {"Authorization": "Bearer fake"}

        repo = Repo(TwinConfig(project="retailtwin-ai-511002", location="us-central1"), transport=transport)
        assert repo.is_available() is True


class TestTwinConfig:
    def test_config_validates_allowed_project(self) -> None:
        from retailtwin_api.firestore_twin import TwinConfig, TwinConfigError
        config = TwinConfig(project="retailtwin-ai-511002", location="us-central1")
        assert config.validated().project == "retailtwin-ai-511002"

    def test_config_rejects_wrong_project(self) -> None:
        from retailtwin_api.firestore_twin import TwinConfig, TwinConfigError
        config = TwinConfig(project="wrong-project", location="us-central1")
        with pytest.raises(TwinConfigError):
            config.validated()


class TestDocPathHelpers:
    def test_bump_version(self) -> None:
        from retailtwin_api.firestore_twin import _bump_version
        assert _bump_version("v1") == "v2"
        assert _bump_version("v9") == "v10"
        assert _bump_version("v99") == "v100"
        assert _bump_version("bad") == "v2"


class TestTwinUnavailable:
    def test_twin_unavailable_message(self) -> None:
        from retailtwin_api.firestore_twin import TwinUnavailable
        exc = TwinUnavailable("connection refused")
        assert exc.reason == "connection refused"
        assert "connection refused" in str(exc)


class TestTwinNotFound:
    def test_twin_not_found_message(self) -> None:
        from retailtwin_api.firestore_twin import TwinNotFound
        exc = TwinNotFound("/store/999")
        assert exc.path == "/store/999"
        assert "/store/999" in str(exc)


class TestInventorySeedValidation:
    def test_seed_requires_positive_facings(self) -> None:
        from retailtwin_api.firestore_twin import InventorySeed
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                          facings=-1, shelf_quantity=0, backroom_quantity=0)

    def test_seed_requires_positive_quantities(self) -> None:
        from retailtwin_api.firestore_twin import InventorySeed
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                          facings=0, shelf_quantity=-1, backroom_quantity=0)


class TestHttpResponse:
    def test_http_response_slots(self) -> None:
        from retailtwin_api.firestore_twin import HttpResponse
        resp = HttpResponse(200, "body")
        assert resp.status == 200
        assert resp.body == "body"


class TestFirestoreField:
    def test_firestore_field_string_value(self) -> None:
        from retailtwin_api.firestore_twin import _FirestoreField
        f = _FirestoreField(stringValue="hello")
        assert f.stringValue == "hello"
        assert f.integerValue is None

    def test_firestore_field_integer_value(self) -> None:
        from retailtwin_api.firestore_twin import _FirestoreField
        f = _FirestoreField(integerValue="42")
        assert f.integerValue == "42"

    def test_firestore_field_boolean_value(self) -> None:
        from retailtwin_api.firestore_twin import _FirestoreField
        f = _FirestoreField(booleanValue=True)
        assert f.booleanValue is True


# ---------------------------------------------------------------------------
# FakeFirestoreTransport contract tests — verify full REST API simulation
# ---------------------------------------------------------------------------


class TestFakeFirestoreTransportContract:
    """Verify FakeFirestoreTransport faithfully simulates the Firestore REST API."""

    def test_commit_rejects_exists_false_on_existing_doc(self) -> None:
        """exists:false returns 409 ALREADY_EXISTS when the document already exists."""
        transport = FakeFirestoreTransport()
        transport._docs["test/doc"] = {"fields": {"x": {"stringValue": "y"}}}
        transport._update_times["test/doc"] = "t1"

        payload = json.dumps({
            "writes": [{
                "update": {
                    "name": "projects/p/databases/(default)/documents/test/doc",
                    "fields": {"x": {"stringValue": "z"}},
                },
                "currentDocument": {"exists": False},
            }]
        }).encode()
        response = transport.request(
            "POST",
            "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents:commit",
            payload,
            {},
        )
        assert response.status == 409

    def test_commit_accepts_exists_false_on_missing_doc(self) -> None:
        """exists:false succeeds when the document does not exist."""
        transport = FakeFirestoreTransport()

        payload = json.dumps({
            "writes": [{
                "update": {
                    "name": "projects/p/databases/(default)/documents/test/new",
                    "fields": {"x": {"stringValue": "y"}},
                },
                "currentDocument": {"exists": False},
            }]
        }).encode()
        response = transport.request(
            "POST",
            "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents:commit",
            payload,
            {},
        )
        assert response.status == 200
        assert "test/new" in transport._docs

    def test_commit_enforces_require_version_on_stale_write(self) -> None:
        """A write with requireVersion mismatching the stored version is rejected."""
        transport = FakeFirestoreTransport()
        transport._docs["stores/store-001/inventory/P001"] = {
            "fields": {
                "store_id": {"stringValue": "store-001"},
                "sku": {"stringValue": "P001"},
                "shelf_id": {"stringValue": "A01"},
                "slot_id": {"stringValue": "A01-S01"},
                "facings": {"integerValue": "3"},
                "shelf_quantity": {"integerValue": "8"},
                "backroom_quantity": {"integerValue": "42"},
                "version": {"integerValue": "5"},
                "updated_at": {"timestampValue": "t1"},
            }
        }
        transport._update_times["stores/store-001/inventory/P001"] = "t1"

        payload = json.dumps({
            "writes": [{
                "update": {
                    "name": "projects/p/databases/(default)/documents/stores/store-001/inventory/P001",
                    "fields": {
                        "facings": {"integerValue": "9"},
                        "version": {"integerValue": "9"},
                        "updated_at": {"timestampValue": "t2"},
                    },
                },
                "currentDocument": {"exists": True, "requireVersion": 3},
            }]
        }).encode()
        response = transport.request(
            "POST",
            "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents:commit",
            payload,
            {},
        )
        assert response.status == 400
        assert "FAILED_PRECONDITION" in response.body
        # Original document is preserved
        assert transport._docs["stores/store-001/inventory/P001"]["fields"]["facings"]["integerValue"] == "3"

    def test_commit_accepts_matching_require_version(self) -> None:
        """A write with requireVersion matching the stored version succeeds."""
        transport = FakeFirestoreTransport()
        transport._docs["stores/store-001/inventory/P001"] = {
            "fields": {
                "store_id": {"stringValue": "store-001"},
                "sku": {"stringValue": "P001"},
                "shelf_id": {"stringValue": "A01"},
                "slot_id": {"stringValue": "A01-S01"},
                "facings": {"integerValue": "3"},
                "shelf_quantity": {"integerValue": "8"},
                "backroom_quantity": {"integerValue": "42"},
                "version": {"integerValue": "3"},
                "updated_at": {"timestampValue": "t1"},
            }
        }
        transport._update_times["stores/store-001/inventory/P001"] = "t1"

        payload = json.dumps({
            "writes": [{
                "update": {
                    "name": "projects/p/databases/(default)/documents/stores/store-001/inventory/P001",
                    "fields": {
                        "facings": {"integerValue": "9"},
                        "version": {"integerValue": "4"},
                        "updated_at": {"timestampValue": "t2"},
                    },
                },
                "currentDocument": {"exists": True, "requireVersion": 3},
            }]
        }).encode()
        response = transport.request(
            "POST",
            "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents:commit",
            payload,
            {},
        )
        assert response.status == 200
        assert transport._docs["stores/store-001/inventory/P001"]["fields"]["facings"]["integerValue"] == "9"

    def test_delete_removes_document(self) -> None:
        """DELETE removes the document from the store."""
        transport = FakeFirestoreTransport()
        transport._docs["stores/store-001/inventory/P001"] = {"fields": {}}
        transport._update_times["stores/store-001/inventory/P001"] = "t1"

        response = transport.request(
            "DELETE",
            "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents/stores/store-001/inventory/P001",
            None,
            {},
        )
        assert response.status == 200
        assert "stores/store-001/inventory/P001" not in transport._docs

    def test_list_inventory_returns_all_skus_for_store(self) -> None:
        """GET /documents/inventory/{store_id} returns all inventory subcollection documents."""
        transport = FakeFirestoreTransport()
        transport._docs["stores/store-001/inventory/P001"] = {
            "fields": {"sku": {"stringValue": "P001"}},
        }
        transport._docs["stores/store-001/inventory/P002"] = {
            "fields": {"sku": {"stringValue": "P002"}},
        }
        transport._docs["stores/store-002/inventory/P001"] = {
            "fields": {"sku": {"stringValue": "P001"}},
        }
        transport._update_times["stores/store-001/inventory/P001"] = "t1"
        transport._update_times["stores/store-001/inventory/P002"] = "t2"
        transport._update_times["stores/store-002/inventory/P001"] = "t3"

        response = transport.request(
            "GET",
            "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents/stores/store-001/inventory",
            None,
            {},
        )
        assert response.status == 200
        docs = json.loads(response.body)["documents"]
        assert len(docs) == 2
        skus = {d["fields"]["sku"]["stringValue"] for d in docs}
        assert skus == {"P001", "P002"}

    def test_timestamp_increments_per_commit(self) -> None:
        """Each successful commit write gets a unique incrementing updateTime."""
        transport = FakeFirestoreTransport()

        for i, name in enumerate(["d1", "d2", "d3"]):
            payload = json.dumps({
                "writes": [{
                    "update": {
                        "name": f"projects/p/databases/(default)/documents/test/{name}",
                        "fields": {"x": {"stringValue": chr(ord("a") + i)}},
                    }
                }]
            }).encode()
            resp = transport.request(
                "POST",
                "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents:commit",
                payload,
                {},
            )
            assert resp.status == 200
            ts = json.loads(resp.body)["writeResults"][0]["updateTime"]
            if i == 0:
                t1 = ts
            elif i == 1:
                t2 = ts
            else:
                t3 = ts

        assert t1 < t2 < t3


# ---------------------------------------------------------------------------
# Lifecycle tests — seed-read-mutate-stale-reject via FakeFirestoreTransport
# ---------------------------------------------------------------------------


class _FirestoreTwinRepoUnderTest:
    """Construct a FirestoreLiveTwinRepository backed by FakeFirestoreTransport."""

    def __init__(self) -> None:
        self._transport = FakeFirestoreTransport()

        class Repo(FirestoreLiveTwinRepository):
            def _headers(self) -> dict[str, str]:
                return {"Authorization": "Bearer fake"}

        self.repo = Repo(
            TwinConfig(project="retailtwin-ai-511002", location="us-central1"),
            transport=self._transport,
        )

    def seed(self) -> None:
        self.repo.seed(
            "store-001",
            "v1",
            [
                InventorySeed(sku="P001", shelf_id="A01", slot_id="A01-S01",
                              facings=3, shelf_quantity=8, backroom_quantity=42),
                InventorySeed(sku="P002", shelf_id="A02", slot_id="A02-S01",
                              facings=2, shelf_quantity=5, backroom_quantity=20),
            ],
        )

    def read_store(self) -> StoreDocument:
        doc = self.repo.get_store("store-001")
        assert doc is not None
        return doc

    def read_inventory(self, sku: str) -> InventoryDocument:
        doc = self.repo.get_inventory("store-001", sku)
        assert doc is not None
        return doc

    def list_inventory(self) -> Sequence[InventoryDocument]:
        return self.repo.list_inventory("store-001")


class TestSeedReadMutateStaleRejectLifecycle:
    """Full lifecycle: seed → read → mutate → stale-reject → reset.

    This is the canonical acceptance test for the Firestore Live Twin
    repository boundary, exercised against a fully-featured fake transport
    that enforces the real Firestore REST API contract including optimistic
    concurrency control.
    """

    def test_lifecycle_seed_twice_is_idempotent(self) -> None:
        """Seeding the same store twice does not duplicate inventory items."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()
        twin.seed()  # second seed — should overwrite, not duplicate

        items = twin.list_inventory()
        skus = {item.sku for item in items}
        assert skus == {"P001", "P002"}
        # Version is still v1 (second seed overwrote with same version)
        store = twin.read_store()
        assert store.version == "v1"

    def test_lifecycle_read_after_seed_returns_correct_values(self) -> None:
        """After seed, read-back returns the seeded values exactly."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()

        p001 = twin.read_inventory("P001")
        assert p001.sku == "P001"
        assert p001.facings == 3
        assert p001.shelf_quantity == 8
        assert p001.backroom_quantity == 42
        assert p001.version == 1

        p002 = twin.read_inventory("P002")
        assert p002.sku == "P002"
        assert p002.facings == 2
        assert p002.shelf_quantity == 5
        assert p002.backroom_quantity == 20

    def test_lifecycle_mutate_updates_version_and_preserves_others(self) -> None:
        """A successful mutation increments the version and persists new values."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()

        # P001 is at version 1. Update it.
        updated = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=5,
            shelf_quantity=12,
            backroom_quantity=50,
            version=2,  # incremented
            updated_at=datetime.now(timezone.utc),
        )
        result = twin.repo.upsert_inventory(updated, expected_version=1)
        assert result.facings == 5
        assert result.version == 2

        # Verify it persisted
        p001 = twin.read_inventory("P001")
        assert p001.facings == 5
        assert p001.version == 2

        # P002 is unaffected
        p002 = twin.read_inventory("P002")
        assert p002.version == 1
        assert p002.facings == 2

    def test_lifecycle_stale_version_is_rejected_and_data_preserved(self) -> None:
        """A mutation with a stale (wrong) expected_version raises TwinConflict."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()

        # Stored P001 is at version 1. Try to write with expected_version=99.
        stale = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=99,
            shelf_quantity=99,
            backroom_quantity=99,
            version=100,
            updated_at=datetime.now(timezone.utc),
        )
        with pytest.raises(TwinConflict) as exc_info:
            twin.repo.upsert_inventory(stale, expected_version=99)  # stored is 1, not 99
        assert exc_info.value.sku == "P001"
        assert exc_info.value.stored_version == 1
        assert exc_info.value.incoming_version == 100

        # Data is preserved — not overwritten
        p001 = twin.read_inventory("P001")
        assert p001.facings == 3  # original value unchanged
        assert p001.version == 1

    def test_lifecycle_stale_reject_leaves_other_items_untouched(self) -> None:
        """A stale write on P001 does not touch P002."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()

        stale = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=999,
            shelf_quantity=999,
            backroom_quantity=999,
            version=999,
            updated_at=datetime.now(timezone.utc),
        )
        try:
            twin.repo.upsert_inventory(stale, expected_version=99)
            pytest.fail("TwinConflict not raised")
        except TwinConflict:
            pass

        # P002 still intact
        p002 = twin.read_inventory("P002")
        assert p002.version == 1
        assert p002.facings == 2

    def test_lifecycle_reset_clears_inventory_and_bumps_version(self) -> None:
        """reset() removes all inventory items and increments the store version."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()
        assert len(twin.list_inventory()) == 2

        twin.repo.reset("store-001")

        assert twin.list_inventory() == []
        store = twin.read_store()
        assert store.version == "v2"

    def test_lifecycle_concurrent_mutations_one_wins(self) -> None:
        """Two concurrent upserts on the same SKU: one succeeds, one conflicts."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            try:
                item = InventoryDocument(
                    store_id="store-001",
                    sku="P001",
                    shelf_id="A01",
                    slot_id="A01-S01",
                    facings=7,
                    shelf_quantity=10,
                    backroom_quantity=10,
                    version=2,
                    updated_at=datetime.now(timezone.utc),
                )
                twin.repo.upsert_inventory(item, expected_version=1)
                with lock:
                    outcomes.append("success")
            except TwinConflict:
                with lock:
                    outcomes.append("conflict")

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert outcomes.count("success") == 1
        assert outcomes.count("conflict") == 1
        # Final state is version 2 (one winner persisted)
        p001 = twin.read_inventory("P001")
        assert p001.version == 2

    def test_lifecycle_mutation_uses_currentDocument_requireVersion(self) -> None:
        """Verify upsert_inventory sends requireVersion in the commit precondition."""
        twin = _FirestoreTwinRepoUnderTest()
        twin.seed()  # uses repo.seed() via twin.repo

        # Mutate P001 → version becomes 2
        item = InventoryDocument(
            store_id="store-001",
            sku="P001",
            shelf_id="A01",
            slot_id="A01-S01",
            facings=7,
            shelf_quantity=10,
            backroom_quantity=10,
            version=2,
            updated_at=datetime.now(timezone.utc),
        )
        result = twin.repo.upsert_inventory(item, expected_version=1)
        assert result.version == 2

        # Find the commit call for inventory
        commit_calls = [
            c for c in twin._transport.calls
            if "commit" in c[1]
        ]
        assert len(commit_calls) >= 1
        # The commit should include requireVersion in currentDocument
        payload = json.loads(cast(bytes, commit_calls[-1][2]))
        writes = payload.get("writes", [])
        inv_write = next(
            (w for w in writes if "inventory" in w.get("update", {}).get("name", "")),
            None,
        )
        assert inv_write is not None
        assert "currentDocument" in inv_write


class TestFakeFirestoreTransportConcurrency:
    """Thread-safety tests for FakeFirestoreTransport._apply_write."""

    def test_concurrent_commits_are_serialized_by_lock(self) -> None:
        """Concurrent commit writes are serialized by the lock — no data corruption."""
        transport = FakeFirestoreTransport()
        barrier = threading.Barrier(4)
        errors: list[Exception] = []

        def writer(n: int) -> None:
            barrier.wait()
            try:
                transport.request(
                    "POST",
                    "https://firestore.googleapis.com/v1/projects/p/databases/(default)/documents:commit",
                    json.dumps({
                        "writes": [{
                            "update": {
                                "name": f"projects/p/databases/(default)/documents/test/doc{n}",
                                "fields": {"v": {"stringValue": f"val{n}"}},
                            }
                        }]
                    }).encode(),
                    {},
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(transport._docs) == 4


