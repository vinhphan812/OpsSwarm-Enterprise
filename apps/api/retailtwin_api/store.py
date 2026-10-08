"""Read the committed day-0 fixture. This is not the Live Twin."""

import json
import re
from pathlib import Path

from pydantic import ValidationError

from retailtwin_api.schemas import FixtureFile, ProductInventory, StoreResponse

_VERSION = re.compile(r"v(?P<number>[0-9]+)\Z")


def parse_version(version: str) -> int:
    match = _VERSION.fullmatch(version)
    if match is None:
        raise ValueError("store version must look like v1")
    return int(match.group("number"))


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
