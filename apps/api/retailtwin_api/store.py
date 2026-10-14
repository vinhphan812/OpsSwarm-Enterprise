"""Store reads: the committed day-0 fixture, or the Live Twin seeded from it."""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import ValidationError

from retailtwin_api.schemas import FixtureFile, ProductInventory, StoreResponse

if TYPE_CHECKING:
    from retailtwin_api.firestore_twin import LiveTwinRepository

_VERSION = re.compile(r"v(?P<number>[0-9]+)\Z")


def parse_version(version: str) -> int:
    match = _VERSION.fullmatch(version)
    if match is None:
        raise ValueError("store version must look like v1")
    return int(match.group("number"))


class StoreReader(Protocol):
    """What the store routes read. The fixture and the Live Twin adapter both satisfy it."""

    store_id: str
    loaded: bool
    error: str | None

    def view(self) -> StoreResponse: ...  # pragma: no branch

    def inventory(self, sku: str) -> ProductInventory | None: ...  # pragma: no branch


def open_store(fixture_path: Path, store_id: str) -> "StoreRepository":
    """Day-0 read adapter.

    Issue #6 replaces this function with Firestore. The replacement must
    keep `loaded`, `store_id`, `view`, and `inventory`. The HTTP routes stay put.
    """
    return StoreRepository(fixture_path, store_id)


class StoreRepository:
    def __init__(self, fixture_path: Path, store_id: str) -> None:
        self.fixture_path = fixture_path
        self.store_id = store_id
        self.loaded = False
        self.error: str | None = None
        self._file: FixtureFile | None = None
        self._version = 0
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
            parsed = FixtureFile.model_validate(payload)
            if parsed.store_id != self.store_id:
                raise ValueError(
                    f"fixture store_id {parsed.store_id!r} does not match {self.store_id!r}"
                )
            version = parse_version(parsed.version)
            skus = [product.sku for product in parsed.products]
            if len(skus) != len(set(skus)):
                raise ValueError("fixture contains a duplicate sku")
            self._file = parsed
            self._version = version
            self.loaded = True
            self.error = None
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            self._file = None
            self.loaded = False
            self.error = str(exc)

    def view(self) -> StoreResponse:
        fixture = self._require()
        return StoreResponse(
            store_id=fixture.store_id,
            context_version=f"{fixture.store_id}:{fixture.version}",
            version=fixture.version,
            products=[self._product(item.sku) for item in fixture.products],
        )

    def inventory(self, sku: str) -> ProductInventory | None:
        fixture = self._require()
        for item in fixture.products:
            if item.sku == sku:
                return self._product(item.sku)
        return None

    def _require(self) -> FixtureFile:
        if self._file is None:
            raise RuntimeError("store fixture is not loaded")
        return self._file

    def _product(self, sku: str) -> ProductInventory:
        fixture = self._require()
        item = next(product for product in fixture.products if product.sku == sku)
        return ProductInventory(
            store_id=fixture.store_id,
            sku=item.sku,
            shelf_id=item.shelf_id,
            slot_id=item.slot_id,
            facings=item.facings,
            shelf_quantity=item.shelf_quantity,
            backroom_quantity=item.backroom_quantity,
            version=self._version,
        )


class LiveTwinStore:
    """Serve `GET /store` and `GET /inventory/{sku}` from the Live Twin.

    Same interface as the fixture `StoreRepository`, so the routes stay put. Reads
    are live: a commit by the guarded Executor shows on the next request.
    """

    def __init__(self, twin: "LiveTwinRepository", store_id: str, error: str | None = None) -> None:
        self.twin = twin
        self.store_id = store_id
        self.error = error
        self.loaded = False
        if error is None:
            self._check()

    def _check(self) -> None:
        try:
            found = self.twin.get_store(self.store_id) is not None
        except Exception as exc:
            self.error = f"Live Twin is not available: {type(exc).__name__}"
            return
        self.loaded = found
        self.error = None if found else f"Store {self.store_id!r} is not in the Live Twin."

    def view(self) -> StoreResponse:
        if not self.loaded:
            raise RuntimeError(self.error or "store is not in the Live Twin")
        store = self.twin.get_store(self.store_id)
        if store is None:
            raise RuntimeError("store is not in the Live Twin")
        return StoreResponse(
            store_id=store.store_id,
            context_version=store.context_version(),
            version=store.version,
            products=[
                ProductInventory.model_validate(item.to_product_inventory())
                for item in sorted(self.twin.list_inventory(self.store_id), key=lambda doc: doc.sku)
            ],
        )

    def inventory(self, sku: str) -> ProductInventory | None:
        if not self.loaded:
            raise RuntimeError(self.error or "store is not in the Live Twin")
        doc = self.twin.get_inventory(self.store_id, sku)
        return ProductInventory.model_validate(doc.to_product_inventory()) if doc is not None else None


def open_memory_live_store(fixture_path: Path, store_id: str) -> LiveTwinStore:
    """An in-process Live Twin seeded from the committed fixture.

    Product versions start at the fixture version, as the fixture store reports
    them. A fixture that does not load leaves the store unloaded with the same error.
    """
    from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventorySeed

    twin = InMemoryTwinRepository()
    fixture = StoreRepository(fixture_path, store_id)
    if not fixture.loaded:
        return LiveTwinStore(twin, store_id, error=fixture.error)
    snapshot = fixture.view()
    twin.seed(
        store_id,
        snapshot.version,
        [
            InventorySeed(
                sku=item.sku,
                shelf_id=item.shelf_id,
                slot_id=item.slot_id,
                facings=item.facings,
                shelf_quantity=item.shelf_quantity,
                backroom_quantity=item.backroom_quantity,
            )
            for item in snapshot.products
        ],
    )
    for item in snapshot.products:
        seeded = twin.get_inventory(store_id, item.sku)
        assert seeded is not None
        twin.upsert_inventory(seeded.model_copy(update={"version": item.version}), expected_version=None)
    return LiveTwinStore(twin, store_id)
