"""Decision Context Guard (DCG) — deterministic enforcement layer.

Core invariant: **No stale decision may commit to live state.**

MVP gates:
1. decision_id is non-empty
2. context_version matches current twin version
3. context_timestamp within 60-second freshness window
4. proposed_actions are structurally valid
5. all action SKUs reference existing slots
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retailtwin_api.demo_runtime.services.twin import TwinService


class DCGVerdict(str, Enum):
    """Outcome of DCG validation."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    REFRESH_REQUIRED = "REFRESH_REQUIRED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


@dataclass
class DCGVerdictResult:
    """Result of DCG.validate()."""
    verdict: DCGVerdict
    decision_id: str
    context_version: str
    current_version: str
    age_seconds: float
    errors: list[str]


@dataclass
class Decision:
    """A candidate decision from the Planner agent."""
    decision_id: str
    context_version: str
    context_timestamp: datetime
    proposed_actions: list[dict]  # list of action dicts


@dataclass
class CommitAuthorization:
    """Short-lived authorization for Executor. Valid for 30 seconds."""
    decision_id: str
    actions: list[dict]
    issued_at: datetime
    expires_at: datetime

    def is_valid(self) -> bool:
        return datetime.now(timezone.utc) < self.expires_at


@dataclass
class ActionValidation:
    """Validation result for a single action."""
    action_type: str
    slot_id: str
    valid: bool
    error: str | None = None


class DCG:
    """Deterministic Decision Context Guard.

    All validation is synchronous and deterministic — no external calls.
    """

    FRESHNESS_SECONDS = 60.0  # decision must be within 60s of current time
    AUTH_TTL_SECONDS = 30.0    # authorization expires after 30s

    def __init__(self, twin: TwinService) -> None:
        self._twin = twin
        self._lock = threading.Lock()
        self._issued_authorizations: list[CommitAuthorization] = []

    def validate(self, decision: Decision) -> DCGVerdictResult:
        """Validate a candidate decision against the current twin state.

        Returns a verdict and details. Does NOT issue authorization.
        """
        errors: list[str] = []
        now = datetime.now(timezone.utc)

        # Gate 1: decision_id must be non-empty
        if not decision.decision_id or not decision.decision_id.strip():
            errors.append("decision_id is empty")

        # Gate 2: context_version must match current twin version
        current_version = self._twin.get_context_version()
        if decision.context_version != current_version:
            errors.append(
                f"context_version mismatch: decision={decision.context_version} "
                f"current={current_version}"
            )

        # Gate 3: context_timestamp must be fresh (within 60s)
        age = (now - decision.context_timestamp).total_seconds()
        if age > self.FRESHNESS_SECONDS:
            errors.append(
                f"decision stale: age={age:.1f}s > {self.FRESHNESS_SECONDS}s threshold"
            )

        # Gate 4: proposed_actions must be structurally valid
        action_errors = self._validate_actions(decision.proposed_actions)
        errors.extend(action_errors)

        if errors:
            if any("version" in e or "stale" in e for e in errors):
                return DCGVerdictResult(
                    verdict=DCGVerdict.REFRESH_REQUIRED,
                    decision_id=decision.decision_id,
                    context_version=decision.context_version,
                    current_version=current_version,
                    age_seconds=age,
                    errors=errors,
                )
            return DCGVerdictResult(
                verdict=DCGVerdict.DENY,
                decision_id=decision.decision_id,
                context_version=decision.context_version,
                current_version=current_version,
                age_seconds=age,
                errors=errors,
            )

        return DCGVerdictResult(
            verdict=DCGVerdict.ALLOW,
            decision_id=decision.decision_id,
            context_version=decision.context_version,
            current_version=current_version,
            age_seconds=age,
            errors=[],
        )

    def _validate_actions(self, actions: list[dict]) -> list[str]:
        """Validate action structure and SKU references."""
        errors = []
        valid_types = {"facings", "replenish", "move"}
        valid_slots = {slot_id for slot_id in self._twin.read().slots}

        for i, action in enumerate(actions):
            atype = action.get("action_type", "")
            slot_id = action.get("slot_id", "")

            if not atype:
                errors.append(f"action[{i}]: missing action_type")
            elif atype not in valid_types:
                errors.append(f"action[{i}]: unknown action_type={atype}")

            if not slot_id:
                errors.append(f"action[{i}]: missing slot_id")
            elif slot_id not in valid_slots:
                errors.append(f"action[{i}]: slot_id={slot_id} not found")

            if atype == "facings" and "facings" not in action:
                errors.append(f"action[{i}]: facings action missing 'facings' field")
            if atype == "replenish" and "quantity" not in action:
                errors.append(f"action[{i}]: replenish action missing 'quantity' field")
            if atype == "move":
                if "from_slot_id" not in action:
                    errors.append(f"action[{i}]: move action missing 'from_slot_id'")
                if "to_slot_id" not in action:
                    errors.append(f"action[{i}]: move action missing 'to_slot_id'")
                if "quantity" not in action:
                    errors.append(f"action[{i}]: move action missing 'quantity'")

        return errors

    def authorize(self, decision: Decision) -> CommitAuthorization | None:
        """Validate and issue a short-lived commit authorization.

        Returns None if validation fails.
        """
        with self._lock:
            result = self.validate(decision)
            if result.verdict != DCGVerdict.ALLOW:
                return None

            now = datetime.now(timezone.utc)
            auth = CommitAuthorization(
                decision_id=decision.decision_id,
                actions=decision.proposed_actions,
                issued_at=now,
                expires_at=now + timedelta(seconds=self.AUTH_TTL_SECONDS),
            )
            self._issued_authorizations.append(auth)
            return auth

    def validate_authorization(self, auth: CommitAuthorization) -> bool:
        """Validate that an authorization is still valid for execution."""
        if datetime.now(timezone.utc) >= auth.expires_at:
            return False
        return True
