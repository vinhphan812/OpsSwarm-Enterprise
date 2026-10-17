import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest

from kpi.evaluator import (
    ASSUMPTIONS,
    FORMULA_ID,
    NO_DEMAND_EVIDENCE_VERSION,
    ChangeFacings,
    KpiError,
    KpiLedger,
    MoveProduct,
    ReplenishShelf,
    SimulationSnapshot,
    SlotState,
    evaluate_candidate,
    schema_required,
)

SCHEMA = Path(__file__).resolve().parents[1] / "kpi" / "kpi-result.schema.json"
OBSERVED = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


def p017() -> SimulationSnapshot:
    return SimulationSnapshot(
        simulation_id="sim-weekend-001",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-weekend-demand-surge-1",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=8,
                backroom_quantity=54,
                facings=2,
                sales_velocity_units_per_hour=Decimal("18.25"),
                price=Decimal("3.5"),
            ),
        ),
    )


def test_doing_nothing_scores_the_weekend_shelf() -> None:
    result = evaluate_candidate(p017(), "baseline", ())

    assert result.formula_id == FORMULA_ID
    assert result.simulation_id == "sim-weekend-001"
    assert result.stockout_risk == "0.15"
    assert result.service_level == "0.11"
    assert result.movement_cost == "0"
    assert result.revenue_benefit == "0"
    assert result.margin_benefit == "0"
    assert result.business_score == "-0.04"
    assert result.movement_units == "0"


def test_candidates_a_b_and_c_repeat_and_stay_ordered() -> None:
    snapshot = p017()
    candidate_a = (ReplenishShelf(sku="P017", quantity=12),)
    candidate_b = (
        ChangeFacings(sku="P017", facings=4),
        ReplenishShelf(sku="P017", quantity=12),
    )
    candidate_c = (
        MoveProduct(sku="P017", from_slot="A02-S03", to_slot="B02-S01"),
        ChangeFacings(sku="P017", facings=4),
        ReplenishShelf(sku="P017", quantity=12),
    )
    ledger = KpiLedger()

    first = [ledger.evaluate(snapshot, name, actions) for name, actions in (("A", candidate_a), ("B", candidate_b), ("C", candidate_c))]
    second = [ledger.evaluate(snapshot, name, actions) for name, actions in (("A", candidate_a), ("B", candidate_b), ("C", candidate_c))]

    assert first == second
    assert [item.candidate_id for item in ledger.results_for("sim-weekend-001")] == ["A", "B", "C"]
    assert all(item.simulation_id == "sim-weekend-001" for item in first)
    assert first[0].service_level == "0.27"
    assert first[0].stockout_risk == "0.15"
    assert first[0].revenue_benefit == "0.16"
    assert first[0].movement_units == "12"
    assert first[0].business_score == "0.12"
    assert first[1].movement_units == "14"
    assert first[1].business_score == "0.09"
    assert first[2].movement_units == "15"
    assert first[2].business_score == "0.07"
    assert Decimal(first[0].business_score) > Decimal(first[1].business_score) > Decimal(first[2].business_score)
    assert snapshot.slots[0].shelf_quantity == 8
    assert snapshot.slots[0].slot_id == "A02-S03"


def test_a_different_action_does_not_replace_the_stored_candidate() -> None:
    ledger = KpiLedger()
    ledger.evaluate(p017(), "A", (ReplenishShelf(sku="P017", quantity=12),))

    with pytest.raises(KpiError, match="different result"):
        ledger.evaluate(p017(), "A", ())


def test_replenish_clears_an_empty_shelf_stockout() -> None:
    snapshot = SimulationSnapshot(
        simulation_id="sim-empty-001",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-empty",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=0,
                backroom_quantity=54,
                facings=2,
                sales_velocity_units_per_hour=Decimal("4"),
            ),
        ),
    )

    before = evaluate_candidate(snapshot, "before", ())
    after = evaluate_candidate(snapshot, "after", (ReplenishShelf(sku="P017", quantity=16),))

    assert before.stockout_risk == "1"
    assert before.service_level == "0"
    assert after.stockout_risk == "0"
    assert after.service_level == "1"
    assert after.movement_units == "16"


def test_invalid_actions_and_snapshots_fail() -> None:
    with pytest.raises(KpiError, match="backroom cannot supply"):
        evaluate_candidate(p017(), "A", (ReplenishShelf(sku="P017", quantity=55),))
    with pytest.raises(KpiError, match="no slot"):
        evaluate_candidate(p017(), "A", (ReplenishShelf(sku="P001", quantity=1),))
    with pytest.raises(KpiError, match="not B01-S01"):
        evaluate_candidate(p017(), "C", (MoveProduct(sku="P017", from_slot="B01-S01", to_slot="B02-S01"),))
    with pytest.raises(KpiError, match="observed_at"):
        evaluate_candidate(
            SimulationSnapshot(
                simulation_id="sim-weekend-001",
                store_id="store-001",
                context_version="store-001:v1",
                correlation_id="run-weekend-demand-surge-1",
                observed_at=datetime(2026, 10, 10, 8, 0),
                slots=p017().slots,
            ),
            "A",
            (),
        )


def test_evidence_matches_the_schema() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    evidence = evaluate_candidate(p017(), "A", (ReplenishShelf(sku="P017", quantity=12),)).as_dict()

    assert schema["additionalProperties"] is False
    assert schema_required(schema) == tuple(evidence)
    assert evidence["assumptions"] == list(ASSUMPTIONS)
    assert set(evidence) == set(schema["properties"])


def test_change_facings_same_count_does_not_add_movement() -> None:
    """Changing facings to the same value adds no movement cost."""
    result = evaluate_candidate(p017(), "A", (ChangeFacings(sku="P017", facings=2),))
    assert result.movement_units == "0"


def test_move_product_to_same_slot_fails() -> None:
    """Moving a product to the slot it already occupies raises."""
    with pytest.raises(KpiError, match="already in"):
        evaluate_candidate(
            p017(), "C",
            (MoveProduct(sku="P017", from_slot="A02-S03", to_slot="A02-S03"),),
        )


def test_move_product_to_occupied_slot_fails() -> None:
    """Moving a product to an occupied slot raises."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-multi-001",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-multi",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=8,
                backroom_quantity=54,
                facings=2,
                sales_velocity_units_per_hour=Decimal("18.25"),
            ),
            SlotState(
                sku="P018",
                slot_id="B02-S01",
                shelf_quantity=4,
                backroom_quantity=20,
                facings=1,
                sales_velocity_units_per_hour=Decimal("5"),
            ),
        ),
    )
    with pytest.raises(KpiError, match="occupied"):
        evaluate_candidate(
            snapshot, "A",
            (MoveProduct(sku="P017", from_slot="A02-S03", to_slot="B02-S01"),),
        )


def test_service_level_is_capped_at_one() -> None:
    """When shelf quantity exceeds needed units, service level is capped at 1."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-overstock-001",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-overstock",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=50,
                backroom_quantity=0,
                facings=2,
                sales_velocity_units_per_hour=Decimal("4"),
            ),
        ),
    )
    result = evaluate_candidate(snapshot, "A", ())
    assert result.service_level == "1"
    assert Decimal(result.business_score) >= 0


def test_occupied_slot_detected_in_snapshot() -> None:
    """A snapshot with duplicate slot_ids raises during validation."""
    with pytest.raises(KpiError, match="used more than once"):
        evaluate_candidate(
            SimulationSnapshot(
                simulation_id="sim-dup-slot",
                store_id="store-001",
                context_version="store-001:v1",
                correlation_id="run-dup-slot",
                observed_at=OBSERVED,
                slots=(
                    SlotState(
                        sku="P017",
                        slot_id="A02-S03",
                        shelf_quantity=8,
                        backroom_quantity=54,
                        facings=2,
                        sales_velocity_units_per_hour=Decimal("18.25"),
                    ),
                    SlotState(
                        sku="P018",
                        slot_id="A02-S03",
                        shelf_quantity=4,
                        backroom_quantity=20,
                        facings=1,
                        sales_velocity_units_per_hour=Decimal("5"),
                    ),
                ),
            ),
            "A",
            (),
        )


def test_duplicate_sku_in_snapshot_raises() -> None:
    """A snapshot with the same SKU on two slots raises during validation."""
    with pytest.raises(KpiError, match="more than one slot"):
        evaluate_candidate(
            SimulationSnapshot(
                simulation_id="sim-dup-sku",
                store_id="store-001",
                context_version="store-001:v1",
                correlation_id="run-dup-sku",
                observed_at=OBSERVED,
                slots=(
                    SlotState(
                        sku="P017",
                        slot_id="A02-S03",
                        shelf_quantity=8,
                        backroom_quantity=54,
                        facings=2,
                        sales_velocity_units_per_hour=Decimal("18.25"),
                    ),
                    SlotState(
                        sku="P017",
                        slot_id="B02-S01",
                        shelf_quantity=4,
                        backroom_quantity=20,
                        facings=1,
                        sales_velocity_units_per_hour=Decimal("5"),
                    ),
                ),
            ),
            "A",
            (),
        )


def test_schema_required_rejects_missing_required_list() -> None:
    """schema_required raises when schema has no required list."""
    with pytest.raises(KpiError, match="required list"):
        schema_required({})


def test_revenue_benefit_is_zero_when_shelf_decreases() -> None:
    """When an action reduces shelf quantity, revenue benefit is 0 (extra is negative)."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-revenue-drop",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-revenue-drop",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=8,
                backroom_quantity=54,
                facings=2,
                sales_velocity_units_per_hour=Decimal("4"),
            ),
        ),
    )
    # No replenishment action — shelf stays at 8. But if we had an action that
    # somehow removed shelf units, revenue benefit should be 0.
    # Since our actions don't remove shelf units, we test the edge case where
    # shelf quantity stays the same: extra = 0, no negative.
    result = evaluate_candidate(snapshot, "A", ())
    assert result.revenue_benefit == "0"


def test_partial_replenishment_never_stockout_risk_not_one() -> None:
    """With partial replenishment (shelf + backroom < demand), stockout risk < 1."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-partial-001",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-partial",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=0,
                backroom_quantity=12,
                facings=2,
                sales_velocity_units_per_hour=Decimal("4"),
            ),
        ),
    )
    # After replenish 12, shelf=12, total=12. Demand=16 (4 units/hr × 4hr).
    # Uncovered = 4, risk = 4/16 = 0.25 < 1.
    result = evaluate_candidate(
        snapshot, "A",
        (ReplenishShelf(sku="P017", quantity=12),),
    )
    assert result.stockout_risk == "0.25"
    assert Decimal(result.stockout_risk) < Decimal("1")


def test_service_level_between_zero_and_one() -> None:
    """Service level is between 0 and 1 when shelf partially covers demand."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-partial-sl-001",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-partial-sl",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=4,
                backroom_quantity=0,
                facings=2,
                sales_velocity_units_per_hour=Decimal("4"),
            ),
        ),
    )
    # shelf=4, demand=16. service_level=4/16=0.25. Not capped.
    result = evaluate_candidate(snapshot, "A", ())
    assert Decimal(result.service_level) > Decimal("0")
    assert Decimal(result.service_level) < Decimal("1")
    assert result.service_level == "0.25"


def test_ledger_stored_result_returned_for_identical_candidate() -> None:
    """KpiLedger.evaluate returns the stored result when called again with same args."""
    ledger = KpiLedger()
    r1 = ledger.evaluate(p017(), "X", (ReplenishShelf(sku="P017", quantity=12),))
    r2 = ledger.evaluate(p017(), "X", (ReplenishShelf(sku="P017", quantity=12),))
    assert r1 is r2  # Same object identity = stored result returned


def test_results_for_returns_empty_when_no_match() -> None:
    """KpiLedger.results_for returns empty tuple when no candidates match."""
    ledger = KpiLedger()
    ledger.evaluate(p017(), "A", (ReplenishShelf(sku="P017", quantity=12),))
    assert ledger.results_for("sim-other") == ()


def test_unknown_action_type_raises() -> None:
    """An action that is not a recognized subtype raises KpiError."""
    from dataclasses import dataclass
    from typing import Union

    @dataclass(frozen=True)
    class FakeAction:
        sku: str

    # A class that is a subtype of ActionUnion but not one of the concrete types
    # We verify by directly calling _apply with a mock action object
    # that doesn't match any isinstance check
    from kpi.evaluator import _apply
    slots = {
        "P017": SlotState(
            "P017", "A02-S03", 8, 54, 2, Decimal("18.25")
        ),
    }
    # Pass a non-Action object directly
    with pytest.raises(KpiError, match="Unknown action"):
        # type: ignore[arg-type]  # intentionally wrong type for test
        _apply(slots, (FakeAction(sku="P017"),))  # type: ignore


def test_snapshot_not_simulation_type_raises() -> None:
    """A non-SimulationSnapshot object passed as snapshot raises."""
    from kpi.evaluator import _snapshot
    with pytest.raises(KpiError, match="simulation snapshot"):
        _snapshot("not a snapshot")  # type: ignore


def test_snapshot_slot_not_slot_type_raises() -> None:
    """A snapshot containing a non-SlotState object raises."""
    from kpi.evaluator import _snapshot
    with pytest.raises(KpiError, match="not a slot"):
        _snapshot(
            SimulationSnapshot(
                simulation_id="sim-001",
                store_id="store-001",
                context_version="v1",
                correlation_id="corr-001",
                observed_at=OBSERVED,
                slots=("not a slot",),  # type: ignore
            )
        )


def test_needed_is_zero_when_sales_velocity_is_zero() -> None:
    """When sales velocity is zero, needed is zero, causing the zero-risk early return."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-zero-velocity",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-zero-velocity",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=8,
                backroom_quantity=54,
                facings=2,
                sales_velocity_units_per_hour=Decimal("0"),
            ),
        ),
    )
    result = evaluate_candidate(snapshot, "A", ())
    assert result.stockout_risk == "0"
    assert result.service_level == "1"


def test_stockout_risk_zero_when_total_needed_is_zero() -> None:
    """When total_needed is zero, stockout_risk is 0 (zero-demand SKU)."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-zero-demand",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-zero-demand",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=0,
                backroom_quantity=0,
                facings=2,
                sales_velocity_units_per_hour=Decimal("0"),
            ),
        ),
    )
    result = evaluate_candidate(snapshot, "A", ())
    # Zero velocity -> zero demand -> zero needed -> zero risk
    assert result.stockout_risk == "0"
    assert result.service_level == "1"
    assert result.movement_cost == "0"


def test_service_level_zero_when_shelf_empty() -> None:
    """When shelf is empty, service level is 0."""
    snapshot = SimulationSnapshot(
        simulation_id="sim-empty-shelf",
        store_id="store-001",
        context_version="store-001:v1",
        correlation_id="run-empty-shelf",
        observed_at=OBSERVED,
        slots=(
            SlotState(
                sku="P017",
                slot_id="A02-S03",
                shelf_quantity=0,
                backroom_quantity=54,
                facings=2,
                sales_velocity_units_per_hour=Decimal("4"),
            ),
        ),
    )
    result = evaluate_candidate(snapshot, "A", ())
    assert result.service_level == "0"


def test_occupied_slot_in_apply_raises() -> None:
    """Moving a product to an occupied slot raises KpiError in _apply."""
    from kpi.evaluator import _apply, SlotState
    slots = {
        "P017": SlotState("P017", "A02-S03", 8, 54, 2, Decimal("18.25")),
        "P018": SlotState("P018", "B02-S01", 4, 20, 1, Decimal("5")),
    }
    from kpi.evaluator import MoveProduct
    with pytest.raises(KpiError, match="occupied"):
        _apply(slots, (MoveProduct("P017", "A02-S03", "B02-S01"),))


def test_revenue_benefit_extra_negative_capped_at_zero() -> None:
    """If extra sellable units would be negative, revenue_benefit is 0."""
    from kpi.evaluator import _extra_sellable, SlotState
    before = SlotState("P017", "A02-S03", 8, 54, 2, Decimal("18.25"))
    after = SlotState("P017", "A02-S03", 5, 57, 2, Decimal("18.25"))  # less shelf
    result = _extra_sellable(before, after, Decimal("8"))
    assert result == Decimal("0")


def test_text_id_rejects_whitespace_only() -> None:
    """_text_id rejects a string that is only whitespace."""
    from kpi.evaluator import _text_id
    with pytest.raises(KpiError, match="required"):
        _text_id("sku", "   ")


def test_count_rejects_negative_value() -> None:
    """_count rejects a negative integer."""
    from kpi.evaluator import _count
    with pytest.raises(KpiError, match="facings"):
        _count("facings", -1, minimum=1)


def test_text_renders_integer_without_decimal_point() -> None:
    """_text renders a value that rounds to a whole number as an integer string."""
    from kpi.evaluator import _text
    from decimal import Decimal
    assert _text(Decimal("1.00")) == "1"
    assert _text(Decimal("0.00")) == "0"
    assert _text(Decimal("10")) == "10"


def test_count_rejects_float_quantity() -> None:
    """_count rejects a float value for quantity."""
    from kpi.evaluator import _count
    with pytest.raises(KpiError, match="quantity"):
        _count("quantity", 1.5, minimum=1)


def test_rate_rejects_negative_price() -> None:
    """_rate rejects a negative decimal value for price."""
    from kpi.evaluator import _rate
    with pytest.raises(KpiError, match="price"):
        _rate("price", Decimal("-0.01"))


def test_count_rejects_non_integer() -> None:
    """_count rejects a non-integer value."""
    from kpi.evaluator import _count
    with pytest.raises(KpiError, match="quantity"):
        _count("quantity", "5", minimum=1)


def test_rate_rejects_non_decimal() -> None:
    """_rate rejects a non-Decimal value."""
    from kpi.evaluator import _rate
    with pytest.raises(KpiError, match="price"):
        _rate("price", "3.50")


def test_rate_rejects_infinity() -> None:
    """_rate rejects an infinite Decimal."""
    from kpi.evaluator import _rate
    with pytest.raises(KpiError, match="price"):
        _rate("price", Decimal("inf"))


# ─── issue #215 — demand-evidence evaluator_version ───────────────────────────


class TestEvaluatorVersionProvenance:
    """Issue #215: the canonical KPI evaluator threads the demand-evidence version.

    ``KpiResult.evaluator_version`` records the deterministic
    sha256[16] digest the BigQuery ``get_sales_history`` reader
    produced for ``query_window`` + ``source_watermark`` +
    ``data_lineage`` + ``content_digest`` (or
    ``NO_DEMAND_EVIDENCE_VERSION`` sentinel when no demand evidence
    was threaded). The agent-level ``SimulationKPIResult`` and
    ``SimulationCandidateResponse`` round-trip the same field so the
    audit trail can prove which evidence snapshot produced the score.
    """

    def test_evaluator_version_round_trips_on_kpi_result(self) -> None:
        result = evaluate_candidate(
            p017(), "baseline", (), evaluator_version="bq-job-abc123"
        )
        assert result.evaluator_version == "bq-job-abc123"
        encoded = result.as_dict()
        assert encoded["evaluator_version"] == "bq-job-abc123"

    def test_default_evaluator_version_is_none_sentinel(self) -> None:
        result = evaluate_candidate(p017(), "baseline", ())
        assert result.evaluator_version == NO_DEMAND_EVIDENCE_VERSION

    def test_evaluator_version_round_trips_through_ledger(self) -> None:
        ledger = KpiLedger()
        first = ledger.evaluate(
            p017(), "A", (ReplenishShelf(sku="P017", quantity=12),),
            evaluator_version="bq-job-run-1",
        )
        # A second ``evaluate`` with the same candidate id and same
        # version returns the stored row (deterministic).
        again = ledger.evaluate(
            p017(), "A", (ReplenishShelf(sku="P017", quantity=12),),
            evaluator_version="bq-job-run-1",
        )
        assert first.evaluator_version == "bq-job-run-1"
        assert again.evaluator_version == "bq-job-run-1"
        assert again is first

    def test_evaluator_version_mismatch_raises_for_same_candidate(self) -> None:
        """A different demand-evidence version for the same candidate must not silently overwrite."""
        ledger = KpiLedger()
        ledger.evaluate(
            p017(), "A", (ReplenishShelf(sku="P017", quantity=12),),
            evaluator_version="bq-job-v1",
        )
        with pytest.raises(KpiError, match="different result"):
            ledger.evaluate(
                p017(), "A", (ReplenishShelf(sku="P017", quantity=12),),
                evaluator_version="bq-job-v2",
            )

    def test_empty_evaluator_version_is_rejected(self) -> None:
        with pytest.raises(KpiError, match="evaluator_version"):
            evaluate_candidate(p017(), "A", (), evaluator_version="")
        with pytest.raises(KpiError, match="evaluator_version"):
            evaluate_candidate(p017(), "A", (), evaluator_version="   ")

    def test_non_string_evaluator_version_is_rejected(self) -> None:
        with pytest.raises(KpiError, match="evaluator_version"):
            evaluate_candidate(p017(), "A", (), evaluator_version=42)  # type: ignore[arg-type]

    def test_evaluator_version_satisfies_kpi_json_schema(self) -> None:
        """The new field must round-trip through the canonical JSON schema."""
        result = evaluate_candidate(
            p017(), "A", (ReplenishShelf(sku="P017", quantity=12),),
            evaluator_version="bq-job-p017-sat",
        )
        encoded = json.loads(json.dumps(result.as_dict(), sort_keys=True))
        jsonschema.validate(encoded, json.loads(SCHEMA.read_text(encoding="utf-8")))
