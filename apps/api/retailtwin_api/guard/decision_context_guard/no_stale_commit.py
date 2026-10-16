"""No-Stale-Commit: re-read the Live Twin immediately before any authorization or commit.

A decision is bound to the exact live entity versions the guard saw when it
allowed it. ``authorize`` runs the guard on fresh reads and returns a
``CommitBinding`` only on ALLOW. ``recheck`` runs the guard again right before
the commit: a SKU that moved is REFRESH_REQUIRED (``VERSION_STALE``), a binding or
context past its expiry is REFRESH_REQUIRED (``CONTEXT_EXPIRED``) whatever
timestamps the decision now carries, and a decision whose
hash no longer matches the binding is DENY (``BINDING_MISMATCH``). Every check
emits a ``GuardAuditEvent``.

The Executor writes with the binding's ``entity_versions`` as the expected
version of each document, so a change that lands between the recheck and the
write is still refused by the Live Twin itself.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from retailtwin_api.contracts import DCGVerdict, DCGVerdictResult, Decision
from retailtwin_api.guard.decision_context_guard.guard import CONTEXT_EXPIRED, DecisionContextGuard

log = logging.getLogger(__name__)

BINDING_MISMATCH = "BINDING_MISMATCH"

Stage = Literal["authorize", "commit"]


class GuardAuditEvent(BaseModel):
    """What the guard decided at one stage, without model text or credentials."""

    model_config = ConfigDict(frozen=True)

    stage: Stage
    decision_id: str
    correlation_id: str
    store_id: str
    verdict: DCGVerdict
    reason_code: str
    failed_gate: str | None
    context_hash: str
    entity_versions: dict[str, str]
    at: datetime
    # Per-gate breakdown the DCG card renders. A failed gate stops the run;
    # later gates carry ``passed=False`` and a "not run" detail. Mirrors the
    # ``policy_result["checks"]`` rows of ``DCGVerdictResult``.
    gate_checks: list[dict[str, object]] = Field(default_factory=list)


class GuardAuditSink(Protocol):
    def record(self, event: GuardAuditEvent) -> None: ...


class InMemoryGuardAudit:
    """Process-memory audit sink. The BigQuery trail is `retailtwin_api.audit.trail`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[GuardAuditEvent] = []

    def record(self, event: GuardAuditEvent) -> None:
        with self._lock:
            self._events.append(event.model_copy(deep=True))

    def events(self, decision_id: str | None = None) -> list[GuardAuditEvent]:
        """Detached copies: changing a returned event never rewrites the stored history."""
        with self._lock:
            return [
                e.model_copy(deep=True)
                for e in self._events
                if decision_id is None or e.decision_id == decision_id
            ]


@dataclass(frozen=True)
class CommitBinding:
    """The exact live context an allowed decision may be committed against.

    ``expiry`` is when the decision's oldest context ages out under the guard policy.
    """

    decision_id: str
    store_id: str
    context_hash: str
    entity_versions: dict[str, int]
    expiry: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoStaleCommit:
    """Bind decisions to live versions and refuse them once those versions move."""

    def __init__(
        self,
        guard: DecisionContextGuard,
        audit: GuardAuditSink,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._guard = guard
        self._audit = audit
        self._clock = clock

    def authorize(self, decision: Decision) -> tuple[DCGVerdictResult, CommitBinding | None]:
        """Evaluate on fresh reads. A binding exists only for ALLOW."""

        result = self._guard.evaluate(decision)
        self._emit("authorize", decision, result)
        if result.verdict is not DCGVerdict.ALLOW:
            return result, None
        return result, CommitBinding(
            decision_id=decision.decision_id,
            store_id=result.policy_result["store_id"],
            context_hash=result.context_hash,
            entity_versions={sku: int(v) for sku, v in result.policy_result["entity_versions"].items()},
            expiry=result.expiry,
        )

    def recheck(self, decision: Decision, binding: CommitBinding) -> DCGVerdictResult:
        """Evaluate again immediately before commit. ALLOW only if nothing the binding names moved."""

        result = self._guard.evaluate(decision)
        now = self._clock()
        if result.verdict is DCGVerdict.ALLOW and now > binding.expiry:
            # The binding's expiry is authoritative. The hash does not cover the
            # decision's timestamps, so refreshed timestamps must not extend it.
            result = _refuse(
                result, DCGVerdict.REFRESH_REQUIRED, CONTEXT_EXPIRED, "The binding expired before the commit.", now
            )
        elif result.verdict is DCGVerdict.ALLOW and result.context_hash != binding.context_hash:
            # Live versions equal the evidence on ALLOW, so a different hash means a
            # different decision id, store or action list than the one authorized.
            result = _refuse(
                result, DCGVerdict.DENY, BINDING_MISMATCH, "The decision is not the one this binding authorized.", now
            )
        self._emit("commit", decision, result)
        return result

    def _emit(self, stage: Stage, decision: Decision, result: DCGVerdictResult) -> None:
        correlation_id = decision.evidence[0].correlation_id if decision.evidence else ""
        raw_checks = result.policy_result.get("checks", [])
        gate_checks: list[dict[str, Any]] = (
            [item for item in raw_checks if isinstance(item, dict)] if isinstance(raw_checks, list) else []
        )
        event = GuardAuditEvent(
            stage=stage,
            decision_id=decision.decision_id,
            correlation_id=correlation_id,
            store_id=result.policy_result.get("store_id", ""),
            verdict=result.verdict,
            reason_code=result.reason_code,
            failed_gate=result.policy_result.get("failed_gate"),
            context_hash=result.context_hash,
            entity_versions=dict(result.policy_result.get("entity_versions", {})),
            at=self._clock(),
            gate_checks=gate_checks,
        )
        self._audit.record(event)
        log.info(
            "dcg %s decision_id=%s correlation_id=%s verdict=%s reason=%s",
            stage,
            decision.decision_id,
            correlation_id,
            result.verdict.value,
            result.reason_code,
        )


def _refuse(
    result: DCGVerdictResult, verdict: DCGVerdict, reason_code: str, detail: str, now: datetime
) -> DCGVerdictResult:
    policy = dict(result.policy_result)
    policy["failed_gate"] = "binding"
    policy["checks"] = [*policy.get("checks", []), {"gate": "binding", "passed": False, "detail": detail}]
    return result.model_copy(
        update={"verdict": verdict, "reason_code": reason_code, "expiry": now, "policy_result": policy}
    )
