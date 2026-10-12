"""Verifier Agent — post-action outcome verification.

Checks post-action outcomes against expected KPIs and triggers re-planning
or rollback policy when verification fails.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retailtwin_api.demo_runtime.services.simulation import SimulationService
    from retailtwin_api.demo_runtime.services.twin import TwinService


class VerifierOutcome(str, Enum):
    """Outcome of post-action verification."""
    PASS = "PASS"
    FAIL = "FAIL"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"


@dataclass
class VerificationCriteria:
    """Criteria for verifying a decision's outcome."""
    decision_id: str
    expected_kpis: dict  # kpi_name -> expected_value
    tolerance: float = 0.1  # 10% tolerance by default


@dataclass
class VerificationResult:
    """Result of post-action verification."""
    decision_id: str
    outcome: VerifierOutcome
    measured_kpis: dict
    expected_kpis: dict
    deviations: dict  # kpi_name -> (measured - expected) / expected
    timestamp: datetime
    recommendation: str


@dataclass
class KPISnapshot:
    """Snapshot of KPI metrics."""
    total_shelf: int
    total_facings: int
    sku_shelf: dict[str, int]
    sku_facings: dict[str, int]
    gap_score: float
    timestamp: datetime


class VerifierAgent:
    """Post-action verification against expected KPIs.

    VerifierAgent does not mutate state — it only reads and reports.
    """

    def __init__(
        self, twin: TwinService, simulation: SimulationService
    ) -> None:
        self._twin = twin
        self._simulation = simulation
        self._lock = threading.Lock()
        self._history: list[VerificationResult] = []

    @property
    def history(self) -> list[VerificationResult]:
        """Audit trail of all verification results."""
        with self._lock:
            return list(self._history)

    def snapshot_kpis(self) -> KPISnapshot:
        """Take a current KPI snapshot from the live twin."""
        state = self._twin.read()
        total_shelf = 0
        total_facings = 0
        sku_shelf: dict[str, int] = {}
        sku_facings: dict[str, int] = {}

        for slot in state.slots.values():
            total_shelf += slot.shelf_quantity
            total_facings += slot.facings
            sku_shelf[slot.sku] = sku_shelf.get(slot.sku, 0) + slot.shelf_quantity
            sku_facings[slot.sku] = sku_facings.get(slot.sku, 0) + slot.facings

        kpi_result = self._simulation.evaluate(
            self._simulation.clone()
        )

        return KPISnapshot(
            total_shelf=total_shelf,
            total_facings=total_facings,
            sku_shelf=sku_shelf,
            sku_facings=sku_facings,
            gap_score=kpi_result.gap_score,
            timestamp=datetime.now(timezone.utc),
        )

    def verify(
        self,
        criteria: VerificationCriteria,
        measured: KPISnapshot,
    ) -> VerificationResult:
        """Verify post-action KPIs against expected criteria."""
        deviations: dict[str, float] = {}
        exceeded = False
        measured_value: float

        for kpi_name, expected_value in criteria.expected_kpis.items():
            if kpi_name == "total_shelf":
                measured_value = float(measured.total_shelf)
            elif kpi_name == "total_facings":
                measured_value = float(measured.total_facings)
            elif kpi_name == "gap_score":
                measured_value = float(measured.gap_score)
            elif kpi_name.startswith("sku_shelf_"):
                sku = kpi_name[len("sku_shelf_") :]
                measured_value = float(measured.sku_shelf.get(sku, 0))
            elif kpi_name.startswith("sku_facings_"):
                sku = kpi_name[len("sku_facings_") :]
                measured_value = float(measured.sku_facings.get(sku, 0))
            else:
                measured_value = 0.0

            if expected_value != 0:
                deviation = abs(measured_value - expected_value) / expected_value
            else:
                deviation = abs(measured_value - expected_value)

            deviations[kpi_name] = deviation
            if deviation > criteria.tolerance:
                exceeded = True

        if exceeded:
            outcome = VerifierOutcome.FAIL
            recommendation = (
                "Verification failed: measured KPIs deviate more than "
                f"{criteria.tolerance * 100:.0f}% from expected. "
                f"Deviations: {deviations}"
            )
        else:
            outcome = VerifierOutcome.PASS
            recommendation = "Verification passed: all KPIs within tolerance."

        result = VerificationResult(
            decision_id=criteria.decision_id,
            outcome=outcome,
            measured_kpis={
                "total_shelf": measured.total_shelf,
                "total_facings": measured.total_facings,
                "gap_score": measured.gap_score,
                "sku_shelf": measured.sku_shelf,
                "sku_facings": measured.sku_facings,
            },
            expected_kpis=criteria.expected_kpis,
            deviations=deviations,
            timestamp=measured.timestamp,
            recommendation=recommendation,
        )

        with self._lock:
            self._history.append(result)

        return result

    def verify_decision(
        self, decision_id: str, expected_kpis: dict, tolerance: float = 0.1
    ) -> VerificationResult:
        """Convenience: snapshot KPIs, verify, and return result."""
        snapshot = self.snapshot_kpis()
        criteria = VerificationCriteria(
            decision_id=decision_id,
            expected_kpis=expected_kpis,
            tolerance=tolerance,
        )
        return self.verify(criteria, snapshot)
