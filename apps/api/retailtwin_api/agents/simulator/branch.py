"""Score planner decisions on a clone of one live snapshot.

The clone and the KPI formula belong to the injected evaluator from issue
#33. This module checks that every decision matches the snapshot, copies the
returned score onto a new decision, and does not write the live snapshot.
"""

from __future__ import annotations

import copy
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
    SimulationKPIResult,
)

log = logging.getLogger(__name__)

FORMULA_ID = "simulation-kpi-v1"
# Default ``evaluator_version`` for the agent-level ``SimulationKPIResult``
# when the underlying canonical evaluator (``services/simulation/kpi/evaluator``)
# did not surface a demand-evidence version. Issue #215 / ADR 0024 threads
# the BigQuery ``retailtwin.sales_events`` job id through the Investigator
# → Planner → Simulator chain; when the chain has none, the simulator
# still produces a deterministic result with this sentinel.
NO_DEMAND_EVIDENCE_VERSION = "none"

INVALID_SNAPSHOT = "invalid_snapshot"
INVALID_REQUEST = "invalid_request"
CONTEXT_MISMATCH = "context_mismatch"
EVALUATION_FAILED = "evaluation_failed"


class SimulationError(Exception):
    """Simulation failed. The message does not include the evaluator error."""

    def __init__(self, correlation_id: str, reason: str) -> None:
        self.correlation_id = correlation_id
        self.reason = reason
        super().__init__(f"Simulation failed for {correlation_id}.")


class CandidateEvaluator(Protocol):
    """Deterministic scorer. Implementations must not call a model."""

    def __call__(
        self,
        snapshot: Mapping[str, Any],
        candidate_id: str,
        actions: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class SlotView:
    sku: str
    slot_id: str
    shelf_quantity: int
    backroom_quantity: int
    facings: int
    sales_velocity_units_per_hour: str
    price: str


@dataclass(frozen=True)
class LiveView:
    """Caller-owned live snapshot. ``simulate`` does not modify it."""

    store_id: str
    context_version: str
    correlation_id: str
    observed_at: datetime
    slots: tuple[SlotView, ...]


@dataclass(frozen=True)
class ScoredCandidate:
    decision: Decision
    kpi: SimulationKPIResult
    evaluation: dict[str, Any]


@dataclass(frozen=True)
class SimulationResult:
    simulation_id: str
    context_version: str
    correlation_id: str
    candidates: tuple[ScoredCandidate, ...]


def _reject(correlation_id: str, reason: str) -> SimulationError:
    log.info(
        "simulation rejected correlation_id=%s reason=%s",
        correlation_id,
        reason,
    )
    return SimulationError(correlation_id, reason)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _whole(value: object, minimum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _decimal(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return value.strip()


def _checked_live(live: LiveView) -> str:
    if not isinstance(live, LiveView):
        raise _reject("unknown", INVALID_SNAPSHOT)
    correlation_id = _text(live.correlation_id)
    if (
        correlation_id is None
        or _text(live.store_id) is None
        or _text(live.context_version) is None
        or not isinstance(live.observed_at, datetime)
        or live.observed_at.tzinfo is None
        or live.observed_at.utcoffset() is None
        or not isinstance(live.slots, tuple)
        or not live.slots
    ):
        raise _reject(correlation_id or "unknown", INVALID_SNAPSHOT)
    seen_sku: set[str] = set()
    seen_slot: set[str] = set()
    for slot in live.slots:
        if not isinstance(slot, SlotView):
            raise _reject(correlation_id, INVALID_SNAPSHOT)
        sku = _text(slot.sku)
        slot_id = _text(slot.slot_id)
        if (
            sku is None
            or slot_id is None
            or sku in seen_sku
            or slot_id in seen_slot
            or _whole(slot.shelf_quantity, 0) is None
            or _whole(slot.backroom_quantity, 0) is None
            or _whole(slot.facings, 1) is None
            or _decimal(slot.sales_velocity_units_per_hour) is None
            or _decimal(slot.price) is None
        ):
            raise _reject(correlation_id, INVALID_SNAPSHOT)
        seen_sku.add(sku)
        seen_slot.add(slot_id)
    return correlation_id


def _snapshot(live: LiveView, simulation_id: str) -> dict[str, Any]:
    return {
        "simulation_id": simulation_id,
        "store_id": live.store_id.strip(),
        "context_version": live.context_version.strip(),
        "correlation_id": live.correlation_id.strip(),
        "observed_at": live.observed_at.isoformat(),
        "slots": [
            {
                "sku": slot.sku.strip(),
                "slot_id": slot.slot_id.strip(),
                "shelf_quantity": slot.shelf_quantity,
                "backroom_quantity": slot.backroom_quantity,
                "facings": slot.facings,
                "sales_velocity_units_per_hour": slot.sales_velocity_units_per_hour.strip(),
                "price": slot.price.strip(),
            }
            for slot in live.slots
        ],
    }


def _action(action: MoveProduct | ChangeFacings | ReplenishShelf) -> dict[str, Any]:
    if isinstance(action, MoveProduct):
        return {
            "type": "move_product",
            "sku": action.sku,
            "from_slot": action.from_slot,
            "to_slot": action.to_slot,
        }
    if isinstance(action, ChangeFacings):
        return {"type": "change_facings", "sku": action.sku, "facings": action.facings}
    if isinstance(action, ReplenishShelf):
        return {"type": "replenish_shelf", "sku": action.sku, "quantity": action.quantity}
    raise TypeError


def _matches(decision: Decision, live: LiveView, correlation_id: str) -> None:
    if decision.context_version.strip() != live.context_version.strip():
        raise _reject(correlation_id, CONTEXT_MISMATCH)
    if not decision.evidence:
        raise _reject(correlation_id, CONTEXT_MISMATCH)
    correlations = {item.correlation_id for item in decision.evidence}
    stores = {item.store_id for item in decision.evidence}
    if correlations != {correlation_id} or stores != {live.store_id.strip()}:
        raise _reject(correlation_id, CONTEXT_MISMATCH)


def _score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError
    return float(number)


def _demand_evidence_version(decision: Decision) -> str | None:
    """Pull the demand-evidence ``source_versions`` entry off ``decision.evidence``.

    Issue #215 / ADR 0024: the canonical demand evidence lives in the
    EvidenceBundle the Investigator produced for ``decision``. The
    bundle's ``source_versions["sales_history"]`` is the deterministic
    sha256[16] digest of ``query_window``, ``source_watermark``,
    ``data_lineage``, and the row-level ``content_digest`` — so two
    distinct BigQuery jobs returning the same rows reproduce the same
    version. The simulator threads this version into the resulting
    ``SimulationKPIResult`` so consumers can see the exact BigQuery
    snapshot the candidate was scored against. Returns ``None`` when
    the decision carries no evidence or the bundle does not include a
    ``sales_history`` version.
    """
    for bundle in decision.evidence:
        version = bundle.source_versions.get("sales_history")
        if isinstance(version, str):
            stripped = version.strip()
            if stripped:
                return stripped
    return None


def _read_evaluator_version(evaluation: Mapping[str, Any]) -> str:
    """Pull the demand-evidence version off the canonical KPI evaluation.

    The canonical scorer in ``services/simulation/kpi/evaluator`` records
    ``evaluator_version`` on the ``KpiResult``. ``SimulationKPIResult``
    round-trips that field so consumers (routes, audit, replan) can see the
    exact BigQuery ``get_sales_history`` job id the candidate was scored
    against (issue #215 / ADR 0024). When the canonical evaluator returns
    an evaluation that omits the field (legacy callers / tests), the agent
    layer falls back to the sentinel ``NO_DEMAND_EVIDENCE_VERSION``.
    """
    raw = evaluation.get("evaluator_version")
    if isinstance(raw, bool):
        return NO_DEMAND_EVIDENCE_VERSION
    if isinstance(raw, str):
        stripped = raw.strip()
        return stripped or NO_DEMAND_EVIDENCE_VERSION
    return NO_DEMAND_EVIDENCE_VERSION


def _checked_evaluation(
    raw: object,
    *,
    simulation_id: str,
    candidate_id: str,
    correlation_id: str,
) -> tuple[dict[str, Any], float]:
    if not isinstance(raw, Mapping):
        raise _reject(correlation_id, EVALUATION_FAILED)
    evaluation = copy.deepcopy(dict(raw))
    if (
        evaluation.get("formula_id") != FORMULA_ID
        or evaluation.get("simulation_id") != simulation_id
        or evaluation.get("candidate_id") != candidate_id
        or evaluation.get("correlation_id") != correlation_id
    ):
        raise _reject(correlation_id, EVALUATION_FAILED)
    try:
        score = _score(evaluation.get("business_score"))
    except (InvalidOperation, ValueError):
        raise _reject(correlation_id, EVALUATION_FAILED) from None
    return evaluation, score


def _ranked_decisions(
    decisions: Sequence[Decision],
    live: LiveView,
    *,
    evaluate: CandidateEvaluator,
    ranker: Any,
    intent: str | None,
    simulation_id: str,
    correlation_id: str,
) -> list[Decision]:
    """Use ``ranker`` to expand + rank the Planner's decisions.

    Imports the optimizer lazily to keep the simulator package's import
    graph minimal when the optimizer is not in use.
    """

    from retailtwin_api.agents.optimizer import (
        InvalidRankerConfig,
        OptimizerError,
        rank_candidates,
        ranked_to_decision,
    )

    try:
        ranked = rank_candidates(
            decisions,
            live,
            kpi_evaluator=evaluate,
            ranker=ranker,
            intent=intent,
            simulation_id=simulation_id,
        )
    except (OptimizerError, InvalidRankerConfig) as exc:
        # ``rank_candidates`` only catches evaluator-side data errors; an
        # unexpected exception (a buggy evaluator, a missing kpi.evaluator
        # module on the calling side, etc.) must surface as a deterministic
        # ``EVALUATION_FAILED`` to match the existing simulator contract.
        log.info(
            "simulation rejected correlation_id=%s reason=%s detail=%s",
            correlation_id,
            EVALUATION_FAILED,
            type(exc).__name__,
        )
        raise SimulationError(correlation_id, EVALUATION_FAILED) from None
    except Exception as exc:  # pragma: no cover - evaluator contract violation
        log.info(
            "simulation rejected correlation_id=%s reason=%s detail=%s",
            correlation_id,
            EVALUATION_FAILED,
            type(exc).__name__,
        )
        raise SimulationError(correlation_id, EVALUATION_FAILED) from None
    if not ranked:
        return []
    base = decisions[0]
    rebuilt: list[Decision] = []
    for entry in ranked:
        rebuilt.append(ranked_to_decision(entry, base=base))
    return rebuilt


def simulate(
    decisions: Sequence[Decision],
    live: LiveView,
    *,
    evaluate: CandidateEvaluator,
    ranker: Any | None = None,
    ranker_intent: str | None = None,
) -> SimulationResult:
    """Score each decision on a clone of ``live``.

    The returned decisions carry ``simulation_id`` and the evaluator's
    business score. ``live`` is not changed. A failed candidate returns no
    partial result.

    When ``ranker`` is provided (the advanced optimizer, issue #54), the
    Planner's two-to-three candidates are replaced with the optimizer's
    ranked output before scoring. The optimizer uses the same evaluator
    to compute the ranker's score; the simulator still scores each ranked
    candidate independently so the returned result is unchanged. The
    ranker is gated by G06 (#53); a ``None`` keeps the existing behaviour.
    """

    correlation_id = _checked_live(live)
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)) or not decisions:
        raise _reject(correlation_id, INVALID_REQUEST)
    if any(not isinstance(decision, Decision) for decision in decisions):
        raise _reject(correlation_id, INVALID_REQUEST)
    identities = [decision.decision_id for decision in decisions]
    if any(not _text(decision_id) for decision_id in identities) or len(set(identities)) != len(identities):
        raise _reject(correlation_id, INVALID_REQUEST)
    for decision in decisions:
        _matches(decision, live, correlation_id)
        try:
            [_action(action) for action in decision.proposed_actions]
        except TypeError:
            raise _reject(correlation_id, INVALID_REQUEST) from None
    if ranker is not None:
        decisions = _ranked_decisions(
            decisions,
            live,
            evaluate=evaluate,
            ranker=ranker,
            intent=ranker_intent,
            simulation_id=f"sim-{correlation_id}",
            correlation_id=correlation_id,
        )
        if not decisions:
            raise _reject(correlation_id, EVALUATION_FAILED)
    simulation_id = f"sim-{correlation_id}"
    payload = _snapshot(live, simulation_id)
    scored: list[ScoredCandidate] = []
    for decision in decisions:
        actions = [_action(action) for action in decision.proposed_actions]
        started = time.perf_counter()
        try:
            raw = evaluate(copy.deepcopy(payload), decision.decision_id, actions)
        except Exception:
            log.info(
                "simulation rejected correlation_id=%s reason=%s",
                correlation_id,
                EVALUATION_FAILED,
            )
            raise SimulationError(correlation_id, EVALUATION_FAILED) from None
        duration_ms = int((time.perf_counter() - started) * 1000)
        evaluation, score = _checked_evaluation(
            raw,
            simulation_id=simulation_id,
            candidate_id=decision.decision_id,
            correlation_id=correlation_id,
        )
        updated = decision.model_copy(
            update={
                "simulation_id": simulation_id,
                "expected_impact": ExpectedImpact(
                    kpi_score=score,
                    description=decision.expected_impact.description,
                ),
            }
        )
        # Thread the demand-evidence version (issue #215 / ADR 0024) end
        # to end. The canonical evaluator returns ``"none"`` when no
        # demand evidence was threaded at evaluation time; the
        # ``_demand_evidence_version`` helper reads the BigQuery job id
        # off the decision's evidence so the SimulationKPIResult carries
        # the exact snapshot the candidate was scored against.
        demand_version = _demand_evidence_version(decision)
        canonical_version = _read_evaluator_version(evaluation)
        scored.append(
            ScoredCandidate(
                decision=updated,
                kpi=SimulationKPIResult(
                    simulation_id=simulation_id,
                    kpi_score=score,
                    duration_ms=duration_ms,
                    evaluator_version=(
                        demand_version
                        if demand_version is not None
                        else canonical_version
                    ),
                ),
                evaluation=evaluation,
            )
        )
    log.info(
        "simulation scored correlation_id=%s simulation_id=%s candidates=%s",
        correlation_id,
        simulation_id,
        len(scored),
    )
    return SimulationResult(
        simulation_id=simulation_id,
        context_version=live.context_version.strip(),
        correlation_id=correlation_id,
        candidates=tuple(scored),
    )
