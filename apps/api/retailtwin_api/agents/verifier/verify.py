"""Re-read Live inventory after a decision and compare it with the actions.

The caller supplies the pre-commit rows. This module applies the decision's
actions to those copies, reads the current rows, and reports VERIFIED,
REGRESSION, or INCONCLUSIVE. It does not write the Live Twin and it does not
recompute a KPI.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Protocol, assert_never

from pydantic import BaseModel, ConfigDict

from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    MoveProduct,
    ReplenishShelf,
    VerifierOutcome,
)
from retailtwin_api.schemas import ProductInventory

log = logging.getLogger(__name__)

# ADR 0012. The planner stores this until simulation scores the candidate.
UNSCORED_KPI = Decimal("-1")

EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"
NO_ACTIONS = "NO_ACTIONS"
BASELINE_MISSING = "BASELINE_MISSING"
ENTITY_UNREADABLE = "ENTITY_UNREADABLE"
READ_FAILED = "READ_FAILED"
STATE_MISMATCH = "STATE_MISMATCH"
KPI_MISMATCH = "KPI_MISMATCH"
KPI_UNOBSERVED = "KPI_UNOBSERVED"
VERIFIED_REASON = "VERIFIED"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REGRESSION = "REGRESSION"
    INCONCLUSIVE = "INCONCLUSIVE"


class InventoryReader(Protocol):
    """Read one current inventory row. Implementations must not be asked to write."""

    def inventory(self, sku: str) -> ProductInventory | None: ...


class SkuCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str
    reason_code: str
    expected: ProductInventory | None = None
    observed: ProductInventory | None = None


class VerificationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str
    correlation_id: str
    store_id: str
    status: VerificationStatus
    reason_code: str
    outcomes: list[VerifierOutcome]
    checks: list[SkuCheck]


class VerificationAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str
    correlation_id: str
    status: VerificationStatus
    reason_code: str
    skus: tuple[str, ...]


class VerificationAudit(Protocol):
    def record(self, event: VerificationAuditEvent) -> None: ...


class InMemoryVerificationAudit:
    """Process-memory audit. The BigQuery trail is issue #35."""

    def __init__(self) -> None:
        self.events: list[VerificationAuditEvent] = []

    def record(self, event: VerificationAuditEvent) -> None:
        self.events.append(event)


def verify(
    decision: Decision,
    before: dict[str, ProductInventory],
    reader: InventoryReader,
    audit: VerificationAudit,
    *,
    correlation_id: str,
    observed_kpi: str | None = None,
) -> VerificationReport:
    """Compare a fresh inventory read with the transition ``decision`` names.

    ``before`` is the pre-commit inventory of every SKU the actions touch.
    ``observed_kpi`` is compared only when ``expected_impact.kpi_score`` is
    not the unscored sentinel ``-1.0``.
    """

    touched = tuple(dict.fromkeys(action.sku for action in decision.proposed_actions))
    store_id = _store_id(decision, correlation_id)
    if store_id is None:
        return _finish(
            decision,
            audit,
            correlation_id=correlation_id,
            store_id="",
            status=VerificationStatus.INCONCLUSIVE,
            reason_code=EVIDENCE_MISMATCH,
            checks=[],
            sku_reasons={sku: EVIDENCE_MISMATCH for sku in touched},
        )
    if not touched:
        return _finish(
            decision,
            audit,
            correlation_id=correlation_id,
            store_id=store_id,
            status=VerificationStatus.INCONCLUSIVE,
            reason_code=NO_ACTIONS,
            checks=[],
            sku_reasons={},
        )

    baseline = _baseline(before, store_id, touched)
    if baseline is None:
        return _finish(
            decision,
            audit,
            correlation_id=correlation_id,
            store_id=store_id,
            status=VerificationStatus.INCONCLUSIVE,
            reason_code=BASELINE_MISSING,
            checks=[],
            sku_reasons={sku: BASELINE_MISSING for sku in touched},
        )

    expected = _expected(decision, baseline)
    checks: list[SkuCheck] = []
    sku_reasons: dict[str, str] = {}
    saw_mismatch = False
    saw_read_failure = False
    read_reason = ENTITY_UNREADABLE
    for sku in touched:
        check, reason = _read_one(reader, decision.decision_id, correlation_id, sku, expected[sku])
        checks.append(check)
        sku_reasons[sku] = reason
        if reason == STATE_MISMATCH:
            saw_mismatch = True
        elif reason in (READ_FAILED, ENTITY_UNREADABLE):
            saw_read_failure = True
            if reason == READ_FAILED:
                read_reason = READ_FAILED

    if saw_mismatch:
        status = VerificationStatus.REGRESSION
        reason_code = STATE_MISMATCH
    elif saw_read_failure:
        status = VerificationStatus.INCONCLUSIVE
        reason_code = read_reason
    else:
        status, reason_code = _kpi_status(decision, observed_kpi)

    return _finish(
        decision,
        audit,
        correlation_id=correlation_id,
        store_id=store_id,
        status=status,
        reason_code=reason_code,
        checks=checks,
        sku_reasons=sku_reasons,
    )


def _store_id(decision: Decision, correlation_id: str) -> str | None:
    correlation_id = correlation_id.strip()
    if not correlation_id or not decision.evidence:
        return None
    stores = {bundle.store_id for bundle in decision.evidence}
    correlations = {bundle.correlation_id for bundle in decision.evidence}
    if len(stores) != 1 or correlations != {correlation_id}:
        return None
    store_id = next(iter(stores)).strip()
    if not store_id:
        return None
    return store_id


def _baseline(
    before: dict[str, ProductInventory], store_id: str, touched: tuple[str, ...]
) -> dict[str, ProductInventory] | None:
    copied: dict[str, ProductInventory] = {}
    for sku in touched:
        row = before.get(sku)
        if row is None or row.sku != sku or row.store_id != store_id:
            return None
        copied[sku] = row.model_copy()
    return copied


def _expected(
    decision: Decision, before: dict[str, ProductInventory]
) -> dict[str, ProductInventory]:
    state = {sku: row.model_copy() for sku, row in before.items()}
    for action in decision.proposed_actions:
        current = state[action.sku]
        if isinstance(action, ReplenishShelf):
            current = current.model_copy(
                update={
                    "shelf_quantity": current.shelf_quantity + action.quantity,
                    "backroom_quantity": current.backroom_quantity - action.quantity,
                }
            )
        elif isinstance(action, ChangeFacings):
            current = current.model_copy(update={"facings": action.facings})
        elif isinstance(action, MoveProduct):
            current = current.model_copy(update={"slot_id": action.to_slot})
        else:
            assert_never(action)
        state[action.sku] = current
    planned: dict[str, ProductInventory] = {}
    for sku, original in before.items():
        planned[sku] = state[sku].model_copy(update={"version": original.version + 1})
    return planned


def _read_one(
    reader: InventoryReader,
    decision_id: str,
    correlation_id: str,
    sku: str,
    expected: ProductInventory,
) -> tuple[SkuCheck, str]:
    try:
        observed = reader.inventory(sku)
    except Exception as exc:
        log.info(
            "verifier.read_failed",
            extra={
                "correlation_id": correlation_id,
                "decision_id": decision_id,
                "sku": sku,
                "error_type": type(exc).__name__,
            },
        )
        return SkuCheck(sku=sku, reason_code=READ_FAILED, expected=expected), READ_FAILED
    if observed is None or observed.sku != sku:
        return SkuCheck(sku=sku, reason_code=ENTITY_UNREADABLE, expected=expected), ENTITY_UNREADABLE
    observed = observed.model_copy()
    if observed.model_dump() != expected.model_dump():
        return (
            SkuCheck(sku=sku, reason_code=STATE_MISMATCH, expected=expected, observed=observed),
            STATE_MISMATCH,
        )
    return SkuCheck(sku=sku, reason_code=VERIFIED_REASON, expected=expected, observed=observed), VERIFIED_REASON


def _kpi_status(decision: Decision, observed_kpi: str | None) -> tuple[VerificationStatus, str]:
    expected = Decimal(str(decision.expected_impact.kpi_score))
    if expected == UNSCORED_KPI:
        return VerificationStatus.VERIFIED, VERIFIED_REASON
    if observed_kpi is None or not observed_kpi.strip():
        return VerificationStatus.INCONCLUSIVE, KPI_UNOBSERVED
    try:
        observed = Decimal(observed_kpi.strip())
    except InvalidOperation:
        return VerificationStatus.INCONCLUSIVE, KPI_UNOBSERVED
    if observed != expected:
        return VerificationStatus.REGRESSION, KPI_MISMATCH
    return VerificationStatus.VERIFIED, VERIFIED_REASON


def _finish(
    decision: Decision,
    audit: VerificationAudit,
    *,
    correlation_id: str,
    store_id: str,
    status: VerificationStatus,
    reason_code: str,
    checks: list[SkuCheck],
    sku_reasons: dict[str, str],
) -> VerificationReport:
    outcomes = [
        VerifierOutcome(
            action_id=f"{decision.decision_id}:{index}",
            verified=sku_reasons.get(action.sku) == VERIFIED_REASON,
            reason=None if sku_reasons.get(action.sku) == VERIFIED_REASON else sku_reasons.get(action.sku, reason_code),
        )
        for index, action in enumerate(decision.proposed_actions)
    ]
    report = VerificationReport(
        decision_id=decision.decision_id,
        correlation_id=correlation_id.strip(),
        store_id=store_id,
        status=status,
        reason_code=reason_code,
        outcomes=outcomes,
        checks=checks,
    )
    audit.record(
        VerificationAuditEvent(
            decision_id=decision.decision_id,
            correlation_id=report.correlation_id,
            status=status,
            reason_code=reason_code,
            skus=tuple(check.sku for check in checks),
        )
    )
    log.info(
        "verifier.checked",
        extra={
            "correlation_id": report.correlation_id,
            "decision_id": decision.decision_id,
            "status": status.value,
            "reason_code": reason_code,
            "store_id": store_id,
        },
    )
    return report
