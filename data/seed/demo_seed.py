"""Canonical seed data for the RetailTwin AI demo scenario.

This module defines the deterministic baseline state for the Weekend Demand Surge
demo scenario. The data is designed to:
- Provide sufficient inventory context for KPI calculations
- Include P017 in a state that demonstrates the demand surge scenario
- Be idempotent: same seed always produces the same data

Seed data structure:
- Store: store-001 (canonical demo store)
- Products: ~20 SKUs including P001 (foundation) and P017 (demand surge target)
- Inventory: Each SKU has shelf_quantity, backroom_quantity, facings
- Scenario: P017 starts with 12 shelf units and 35 backroom units

The demand-surge events (from data/synthetic/weekend-demand-surge.json) will
sell through ~73 units in a 4-hour window, demonstrating the AI's ability to
detect the surge and recommend replenishment/facings changes.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

# Canonical constants
CANONICAL_STORE_ID: Final[str] = "store-001"
CANONICAL_SEED_VERSION: Final[str] = "v1"
CANONICAL_SEED_TIMESTAMP: Final[str] = "2026-10-09T00:00:00Z"

# P017 is the demand-surge SKU
P017_SLOT: Final[str] = "A02-S03"
P017_SHELF: Final[str] = "A02"
P017_SHELF_QTY: Final[int] = 12
P017_BACKROOM_QTY: Final[int] = 35
P017_FACINGS: Final[int] = 3  # Initially limited facings that the demo will increase


@dataclass(frozen=True)
class SeedProduct:
    """One product's seed data for the Live Twin."""
    sku: str
    shelf_id: str
    slot_id: str
    facings: int
    shelf_quantity: int
    backroom_quantity: int


# Canonical demo products for the Weekend Demand Surge scenario
# P001 is the foundation (from the day-0 fixture)
# P017 is the demand-surge target
# Other products provide realistic store context
DEMO_PRODUCTS: tuple[SeedProduct, ...] = (
    # Foundation product (from day-0 fixture)
    SeedProduct(
        sku="P001",
        shelf_id="A01",
        slot_id="A01-S01",
        facings=3,
        shelf_quantity=8,
        backroom_quantity=42,
    ),
    # P017 - Demand Surge Target (this SKU triggers the demo scenario)
    SeedProduct(
        sku="P017",
        shelf_id=P017_SHELF,
        slot_id=P017_SLOT,
        facings=P017_FACINGS,
        shelf_quantity=P017_SHELF_QTY,
        backroom_quantity=P017_BACKROOM_QTY,
    ),
    # Supporting products for realistic store context
    SeedProduct(
        sku="P002",
        shelf_id="A01",
        slot_id="A01-S02",
        facings=2,
        shelf_quantity=10,
        backroom_quantity=30,
    ),
    SeedProduct(
        sku="P003",
        shelf_id="A01",
        slot_id="A01-S03",
        facings=2,
        shelf_quantity=5,
        backroom_quantity=25,
    ),
    SeedProduct(
        sku="P004",
        shelf_id="A02",
        slot_id="A02-S01",
        facings=3,
        shelf_quantity=15,
        backroom_quantity=40,
    ),
    SeedProduct(
        sku="P005",
        shelf_id="A02",
        slot_id="A02-S02",
        facings=4,
        shelf_quantity=20,
        backroom_quantity=50,
    ),
    SeedProduct(
        sku="P006",
        shelf_id="B01",
        slot_id="B01-S01",
        facings=2,
        shelf_quantity=8,
        backroom_quantity=20,
    ),
    SeedProduct(
        sku="P007",
        shelf_id="B01",
        slot_id="B01-S02",
        facings=3,
        shelf_quantity=12,
        backroom_quantity=35,
    ),
    SeedProduct(
        sku="P008",
        shelf_id="B02",
        slot_id="B02-S01",
        facings=2,
        shelf_quantity=6,
        backroom_quantity=18,
    ),
    SeedProduct(
        sku="P009",
        shelf_id="B02",
        slot_id="B02-S02",
        facings=4,
        shelf_quantity=18,
        backroom_quantity=45,
    ),
    SeedProduct(
        sku="P010",
        shelf_id="C01",
        slot_id="C01-S01",
        facings=3,
        shelf_quantity=14,
        backroom_quantity=38,
    ),
    # Low-stock product for contrast
    SeedProduct(
        sku="P011",
        shelf_id="C01",
        slot_id="C01-S02",
        facings=2,
        shelf_quantity=3,
        backroom_quantity=12,
    ),
    # High-velocity product
    SeedProduct(
        sku="P012",
        shelf_id="C02",
        slot_id="C02-S01",
        facings=5,
        shelf_quantity=25,
        backroom_quantity=60,
    ),
    # Slow-moving product
    SeedProduct(
        sku="P013",
        shelf_id="C02",
        slot_id="C02-S02",
        facings=2,
        shelf_quantity=8,
        backroom_quantity=22,
    ),
    # Another category product
    SeedProduct(
        sku="P014",
        shelf_id="D01",
        slot_id="D01-S01",
        facings=3,
        shelf_quantity=11,
        backroom_quantity=28,
    ),
    SeedProduct(
        sku="P015",
        shelf_id="D01",
        slot_id="D01-S02",
        facings=2,
        shelf_quantity=7,
        backroom_quantity=19,
    ),
    # Frozen/chiller products
    SeedProduct(
        sku="P016",
        shelf_id="GDC01",
        slot_id="GDC01-S01",
        facings=3,
        shelf_quantity=16,
        backroom_quantity=42,
    ),
    # Empty slot placeholder (demonstrates stockout risk)
    SeedProduct(
        sku="P018",
        shelf_id="GDC01",
        slot_id="GDC01-S02",
        facings=2,
        shelf_quantity=0,  # Stockout
        backroom_quantity=24,
    ),
    # Open chiller products
    SeedProduct(
        sku="P019",
        shelf_id="OC01",
        slot_id="OC01-S01",
        facings=4,
        shelf_quantity=22,
        backroom_quantity=55,
    ),
    SeedProduct(
        sku="P020",
        shelf_id="OC01",
        slot_id="OC01-S02",
        facings=3,
        shelf_quantity=9,
        backroom_quantity=27,
    ),
)


def get_seed_products() -> tuple[SeedProduct, ...]:
    """Return the canonical demo seed products."""
    return DEMO_PRODUCTS


def get_p017_seed() -> SeedProduct:
    """Return the P017 seed product (demand surge target)."""
    for product in DEMO_PRODUCTS:
        if product.sku == "P017":
            return product
    raise ValueError("P017 not found in seed data")


def total_shelf_quantity() -> int:
    """Calculate total shelf quantity across all products."""
    return sum(p.shelf_quantity for p in DEMO_PRODUCTS)


def total_backroom_quantity() -> int:
    """Calculate total backroom quantity across all products."""
    return sum(p.backroom_quantity for p in DEMO_PRODUCTS)


def validate_seed() -> list[str]:
    """Validate seed data consistency. Returns list of warnings."""
    warnings = []

    # Check for duplicate SKUs
    skus = [p.sku for p in DEMO_PRODUCTS]
    if len(skus) != len(set(skus)):
        warnings.append("Duplicate SKU found in seed data")

    # Check P017 is present
    if "P017" not in skus:
        warnings.append("P017 (demand surge target) is missing from seed data")

    # Check for zero stockout products
    for p in DEMO_PRODUCTS:
        if p.shelf_quantity == 0:
            warnings.append(f"{p.sku} has zero shelf_quantity (stockout)")

    return warnings
