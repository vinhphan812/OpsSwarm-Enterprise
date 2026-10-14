"""Post-action verifier: fresh inventory reads, no Live Twin writes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from retailtwin_api.agents.verifier.verify import (
    BASELINE_MISSING,
    ENTITY_UNREADABLE,
    EVIDENCE_MISMATCH,
    KPI_MISMATCH,
    KPI_UNOBSERVED,
    NO_ACTIONS,
    READ_FAILED,
    STATE_MISMATCH,
    VERIFIED_REASON,
    InMemoryVerificationAudit,
    VerificationStatus,
    verify,
)
from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    EvidenceBundle,
    EvidenceItem,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.schemas import ProductInventory

CORRELATION_ID = "run-weekend-demand-surge-1"
COLLECTED_AT = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


class MemoryReader:
    def __init__(self, rows: dict[str, ProductInventory]) -> None:
        self.rows = rows
        self.calls: list[str] = []
        self.writes: list[str] = []

    def inventory(self, sku: str) -> ProductInventory | None:
        self.calls.append(sku)
        return self.rows.get(sku)


class RaisingReader:
    def inventory(self, sku: str) -> ProductInventory | None:
        raise RuntimeError("secret token")


def _row(**overrides: object) -> ProductInventory:
    values: dict[str, object] = {
        "store_id": "store-001",
        "sku": "P017",
        "shelf_id": "A02",
        "slot_id": "A02-S03",
        "facings": 2,
        "shelf_quantity": 8,
        "backroom_quantity": 54,
        "version": 1,
    }
    values.update(overrides)
    return ProductInventory.model_validate(values)


def _decision(*actions: object, score: float = -1.0, correlation_id: str = CORRELATION_ID, store_id: str = "store-001") -> Decision:
    return Decision(
        decision_id="dec-p017-replenish",
        agent_id="retailtwin-planner",
        context_version="store-001:v1",
        context_timestamp=COLLECTED_AT,
        evidence=[
            EvidenceBundle(
                bundle_id="bundle-p017",
                provenance="investigator",
                source="inventory",
                entity_versions={"P017": "1"},
                collected_at=COLLECTED_AT,
                freshness=COLLECTED_AT,
                store_id=store_id,
                correlation_id=correlation_id,
                is_sufficient=True,
                items=[EvidenceItem(event_type="inventory", payload={"sku": "P017"})],
            )
        ],
        proposed_actions=list(actions),
        simulation_id=None,
        expected_impact=ExpectedImpact(kpi_score=score, description="replenish the weekend shelf"),
    )


def test_replenish_matches_the_reread() -> None:
    before = _row()
    observed = _row(shelf_quantity=20, backroom_quantity=42, version=2)
    reader = MemoryReader({"P017": observed})
    audit = InMemoryVerificationAudit()
    snapshot = before.model_dump()

    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": before},
        reader,
        audit,
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.VERIFIED
    assert report.reason_code == VERIFIED_REASON
    assert report.store_id == "store-001"
    assert reader.calls == ["P017"]
    assert reader.writes == []
    assert before.model_dump() == snapshot
    assert report.outcomes[0].verified is True
    assert report.outcomes[0].action_id == "dec-p017-replenish:0"
    assert report.outcomes[0].reason is None
    assert report.checks[0].observed == observed
    assert audit.events[0].status is VerificationStatus.VERIFIED
    assert audit.events[0].skus == ("P017",)
    assert audit.events[0].correlation_id == CORRELATION_ID


def test_shelf_mismatch_is_regression() -> None:
    reader = MemoryReader({"P017": _row(shelf_quantity=19, backroom_quantity=42, version=2)})
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row()},
        reader,
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.REGRESSION
    assert report.reason_code == STATE_MISMATCH
    assert report.outcomes[0].verified is False
    assert report.outcomes[0].reason == STATE_MISMATCH


def test_version_that_did_not_advance_is_regression() -> None:
    reader = MemoryReader({"P017": _row(shelf_quantity=20, backroom_quantity=42, version=1)})
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row()},
        reader,
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.REGRESSION
    assert report.reason_code == STATE_MISMATCH


def test_move_changes_only_the_slot() -> None:
    observed = _row(slot_id="B02-S01", version=2)
    report = verify(
        _decision(MoveProduct(sku="P017", from_slot="A02-S03", to_slot="B02-S01")),
        {"P017": _row()},
        MemoryReader({"P017": observed}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.VERIFIED
    assert report.checks[0].expected is not None
    assert report.checks[0].expected.slot_id == "B02-S01"
    assert report.checks[0].expected.shelf_id == "A02"
    assert report.checks[0].expected.shelf_quantity == 8


def test_facings_then_replenish_apply_in_order() -> None:
    observed = _row(facings=4, shelf_quantity=20, backroom_quantity=42, version=2)
    report = verify(
        _decision(
            ChangeFacings(sku="P017", facings=4),
            ReplenishShelf(sku="P017", quantity=12),
        ),
        {"P017": _row()},
        MemoryReader({"P017": observed}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.VERIFIED
    assert [item.verified for item in report.outcomes] == [True, True]
    assert [item.action_id for item in report.outcomes] == [
        "dec-p017-replenish:0",
        "dec-p017-replenish:1",
    ]


def test_one_mismatched_sku_regresses_the_decision() -> None:
    decision = _decision(
        ReplenishShelf(sku="P017", quantity=12),
        ReplenishShelf(sku="P001", quantity=1),
    )
    decision.evidence[0].entity_versions["P001"] = "1"
    before = {
        "P017": _row(),
        "P001": _row(sku="P001", shelf_id="A01", slot_id="A01-S01", shelf_quantity=4, backroom_quantity=10),
    }
    reader = MemoryReader(
        {
            "P017": _row(shelf_quantity=20, backroom_quantity=42, version=2),
            "P001": _row(sku="P001", shelf_id="A01", slot_id="A01-S01", shelf_quantity=4, backroom_quantity=10, version=2),
        }
    )
    report = verify(decision, before, reader, InMemoryVerificationAudit(), correlation_id=CORRELATION_ID)

    assert report.status is VerificationStatus.REGRESSION
    assert [item.verified for item in report.outcomes] == [True, False]


def test_unread_sku_is_inconclusive_when_nothing_mismatches() -> None:
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row()},
        MemoryReader({}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.INCONCLUSIVE
    assert report.reason_code == ENTITY_UNREADABLE
    assert report.outcomes[0].verified is False


def test_mismatch_wins_over_an_unread_sku() -> None:
    decision = _decision(
        ReplenishShelf(sku="P017", quantity=12),
        ReplenishShelf(sku="P001", quantity=1),
    )
    before = {
        "P017": _row(),
        "P001": _row(sku="P001", shelf_id="A01", slot_id="A01-S01"),
    }
    reader = MemoryReader({"P017": _row(shelf_quantity=1, backroom_quantity=61, version=2)})
    report = verify(decision, before, reader, InMemoryVerificationAudit(), correlation_id=CORRELATION_ID)

    assert report.status is VerificationStatus.REGRESSION
    assert report.reason_code == STATE_MISMATCH


def test_read_failure_is_inconclusive_and_hides_the_exception_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row()},
        RaisingReader(),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.INCONCLUSIVE
    assert report.reason_code == READ_FAILED
    failed = next(record for record in caplog.records if record.getMessage() == "verifier.read_failed")
    assert getattr(failed, "correlation_id") == CORRELATION_ID
    assert getattr(failed, "error_type") == "RuntimeError"
    rendered = " ".join(str(value) for record in caplog.records for value in record.__dict__.values())
    assert "secret token" not in rendered


def test_wrong_sku_on_the_read_is_unreadable() -> None:
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row()},
        MemoryReader({"P017": _row(sku="P001", shelf_quantity=20, backroom_quantity=42, version=2)}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.reason_code == ENTITY_UNREADABLE


def test_missing_baseline_does_not_read() -> None:
    reader = MemoryReader({"P017": _row(version=2)})
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {},
        reader,
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.INCONCLUSIVE
    assert report.reason_code == BASELINE_MISSING
    assert reader.calls == []


def test_blank_store_and_wrong_baseline_sku_are_inconclusive() -> None:
    blank = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12), store_id="  "),
        {"P017": _row()},
        MemoryReader({}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )
    wrong_sku = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row(sku="P001")},
        MemoryReader({}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert blank.reason_code == EVIDENCE_MISMATCH
    assert wrong_sku.reason_code == BASELINE_MISSING


def test_baseline_from_another_store_is_missing() -> None:
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row(store_id="store-002")},
        MemoryReader({}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.reason_code == BASELINE_MISSING


def test_no_actions_is_inconclusive() -> None:
    reader = MemoryReader({})
    report = verify(
        _decision(),
        {},
        reader,
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.status is VerificationStatus.INCONCLUSIVE
    assert report.reason_code == NO_ACTIONS
    assert report.outcomes == []
    assert reader.calls == []


def test_correlation_mismatch_is_inconclusive() -> None:
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12)),
        {"P017": _row()},
        MemoryReader({}),
        InMemoryVerificationAudit(),
        correlation_id="other-run",
    )

    assert report.reason_code == EVIDENCE_MISMATCH
    assert report.store_id == ""


def test_empty_evidence_is_inconclusive() -> None:
    decision = _decision(ReplenishShelf(sku="P017", quantity=12))
    decision.evidence = []
    report = verify(
        decision,
        {"P017": _row()},
        MemoryReader({}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
    )

    assert report.reason_code == EVIDENCE_MISMATCH


def test_scored_kpi_must_match_the_observed_decimal() -> None:
    decision = _decision(ReplenishShelf(sku="P017", quantity=12), score=0.12)
    before = {"P017": _row()}
    reader = MemoryReader({"P017": _row(shelf_quantity=20, backroom_quantity=42, version=2)})

    matched = verify(decision, before, reader, InMemoryVerificationAudit(), correlation_id=CORRELATION_ID, observed_kpi="0.12")
    missed = verify(decision, before, reader, InMemoryVerificationAudit(), correlation_id=CORRELATION_ID, observed_kpi="0.09")
    missing = verify(decision, before, reader, InMemoryVerificationAudit(), correlation_id=CORRELATION_ID)

    assert matched.status is VerificationStatus.VERIFIED
    assert missed.status is VerificationStatus.REGRESSION
    assert missed.reason_code == KPI_MISMATCH
    assert missed.outcomes[0].verified is True
    assert missing.status is VerificationStatus.INCONCLUSIVE
    assert missing.reason_code == KPI_UNOBSERVED


def test_unscored_sentinel_does_not_compare_a_kpi() -> None:
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12), score=-1.0),
        {"P017": _row()},
        MemoryReader({"P017": _row(shelf_quantity=20, backroom_quantity=42, version=2)}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
        observed_kpi="0.12",
    )

    assert report.status is VerificationStatus.VERIFIED


def test_garbage_observed_kpi_is_inconclusive() -> None:
    report = verify(
        _decision(ReplenishShelf(sku="P017", quantity=12), score=0.12),
        {"P017": _row()},
        MemoryReader({"P017": _row(shelf_quantity=20, backroom_quantity=42, version=2)}),
        InMemoryVerificationAudit(),
        correlation_id=CORRELATION_ID,
        observed_kpi="not-a-score",
    )

    assert report.reason_code == KPI_UNOBSERVED
