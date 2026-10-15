#!/usr/bin/env python3
"""Validate seed data for the RetailTwin AI demo.

This script validates the deterministic seed data to ensure:
- All required SKUs are present
- P017 (demand surge target) has correct values
- No duplicate SKUs
- Total inventory quantities are consistent
- Demand surge events match expected pattern
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from data.seed.demo_seed import (
    DEMO_PRODUCTS,
    CANONICAL_STORE_ID,
    CANONICAL_SEED_VERSION,
    P017_SLOT,
    P017_SHELF,
    P017_SHELF_QTY,
    P017_BACKROOM_QTY,
    P017_FACINGS,
    get_p017_seed,
    total_shelf_quantity,
    total_backroom_quantity,
    validate_seed,
)


def validate_seed_data() -> list[str]:
    """Validate seed data consistency. Returns list of issues."""
    issues = []

    # Check for duplicate SKUs
    skus = [p.sku for p in DEMO_PRODUCTS]
    if len(skus) != len(set(skus)):
        issues.append("Duplicate SKU found in seed data")

    # Check P017 is present
    p017 = get_p017_seed()
    if p017.shelf_id != P017_SHELF:
        issues.append(f"P017 shelf_id mismatch: expected {P017_SHELF}, got {p017.shelf_id}")
    if p017.slot_id != P017_SLOT:
        issues.append(f"P017 slot_id mismatch: expected {P017_SLOT}, got {p017.slot_id}")
    if p017.shelf_quantity != P017_SHELF_QTY:
        issues.append(f"P017 shelf_quantity mismatch: expected {P017_SHELF_QTY}, got {p017.shelf_quantity}")
    if p017.backroom_quantity != P017_BACKROOM_QTY:
        issues.append(f"P017 backroom_quantity mismatch: expected {P017_BACKROOM_QTY}, got {p017.backroom_quantity}")
    if p017.facings != P017_FACINGS:
        issues.append(f"P017 facings mismatch: expected {P017_FACINGS}, got {p017.facings}")

    # Check P001 is present (foundation product)
    p001 = next((p for p in DEMO_PRODUCTS if p.sku == "P001"), None)
    if p001 is None:
        issues.append("P001 (foundation product) is missing from seed data")

    # Check all products have valid quantities
    for p in DEMO_PRODUCTS:
        if p.shelf_quantity < 0:
            issues.append(f"{p.sku} has negative shelf_quantity")
        if p.backroom_quantity < 0:
            issues.append(f"{p.sku} has negative backroom_quantity")
        if p.facings < 0:
            issues.append(f"{p.sku} has negative facings")

    return issues


def validate_weekend_demand_surge() -> list[str]:
    """Validate the weekend demand surge scenario."""
    issues = []

    # Load the fixture
    fixture_path = REPO_ROOT / "data" / "synthetic" / "weekend-demand-surge.json"
    try:
        with open(fixture_path) as f:
            fixture = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        issues.append(f"Cannot read weekend-demand-surge.json: {e}")
        return issues

    # Check seed value
    if fixture.get("seed") != 1:
        issues.append(f"Expected seed=1, got {fixture.get('seed')}")

    # Check store_id
    if fixture.get("store_id") != CANONICAL_STORE_ID:
        issues.append(f"Expected store_id={CANONICAL_STORE_ID}, got {fixture.get('store_id')}")

    # Check SKU
    if fixture.get("sku") != "P017":
        issues.append(f"Expected sku=P017, got {fixture.get('sku')}")

    # Check events exist
    events = fixture.get("events", [])
    if len(events) != 13:
        issues.append(f"Expected 13 events, got {len(events)}")

    # Calculate baseline units (Friday)
    baseline_events = [e for e in events if "base" in e.get("event_id", "")]
    baseline_units = sum(e.get("quantity", 0) for e in baseline_events)
    if baseline_units != 50:
        issues.append(f"Baseline units should be 50, got {baseline_units}")

    # Calculate surge units (Saturday)
    surge_events = [e for e in events if "surge" in e.get("event_id", "")]
    surge_units = sum(e.get("quantity", 0) for e in surge_events)
    if surge_units != 73:
        issues.append(f"Surge units should be 73, got {surge_units}")

    # Calculate increase
    if baseline_units > 0:
        increase = (surge_units - baseline_units) / baseline_units
        expected_increase = 0.46
        if abs(increase - expected_increase) > 0.01:
            issues.append(f"Increase should be ~0.46, got {increase:.3f}")

    # Check correlation_id consistency
    correlation_ids = set(e.get("correlation_id") for e in events)
    if len(correlation_ids) != 1:
        issues.append(f"Events should have one correlation_id, got {len(correlation_ids)}")

    return issues


def validate_demo_seed_module() -> list[str]:
    """Validate the demo_seed module."""
    issues = []

    # Check version
    if CANONICAL_SEED_VERSION != "v1":
        issues.append(f"Expected version v1, got {CANONICAL_SEED_VERSION}")

    # Check store_id
    if CANONICAL_STORE_ID != "store-001":
        issues.append(f"Expected store_id store-001, got {CANONICAL_STORE_ID}")

    # Check total quantities
    total_shelf = total_shelf_quantity()
    total_backroom = total_backroom_quantity()

    if total_shelf <= 0:
        issues.append(f"Total shelf quantity should be positive, got {total_shelf}")
    if total_backroom <= 0:
        issues.append(f"Total backroom quantity should be positive, got {total_backroom}")

    return issues


def main() -> int:
    print("=" * 60)
    print("RETAILTWIN AI - SEED DATA VALIDATION")
    print("=" * 60)
    print()

    all_issues: list[str] = []

    # Validate seed data
    print("Validating demo_seed module...")
    issues = validate_demo_seed_module()
    if issues:
        all_issues.extend([f"  demo_seed: {i}" for i in issues])
        print(f"  FAILED: {len(issues)} issues")
    else:
        print("  OK")

    # Validate seed data consistency
    print()
    print("Validating seed data consistency...")
    issues = validate_seed_data()
    if issues:
        all_issues.extend([f"  seed_data: {i}" for i in issues])
        print(f"  FAILED: {len(issues)} issues")
    else:
        print("  OK")

    # Validate weekend demand surge
    print()
    print("Validating weekend demand surge fixture...")
    issues = validate_weekend_demand_surge()
    if issues:
        all_issues.extend([f"  surge: {i}" for i in issues])
        print(f"  FAILED: {len(issues)} issues")
    else:
        print("  OK")

    # Summary
    print()
    print("=" * 60)
    if all_issues:
        print("VALIDATION FAILED")
        print("=" * 60)
        for issue in all_issues:
            print(issue)
        return 1
    else:
        print("VALIDATION PASSED")
        print("=" * 60)

        # Show summary
        print()
        print("Seed Data Summary:")
        print(f"  Products: {len(DEMO_PRODUCTS)}")
        print(f"  Total shelf quantity: {total_shelf_quantity()}")
        print(f"  Total backroom quantity: {total_backroom_quantity()}")
        print(f"  P017: shelf={P017_SHELF_QTY}, backroom={P017_BACKROOM_QTY}, facings={P017_FACINGS}")

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
