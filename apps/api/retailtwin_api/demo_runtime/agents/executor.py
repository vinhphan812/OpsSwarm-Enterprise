"""Executor Agent — executes only authorized actions.

The Executor executes actions only when presented with a valid, non-expired
CommitAuthorization issued by the DCG. It is the sole mutation path for the Live Twin.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from retailtwin_api.demo_runtime.guard.decision_context_guard import CommitAuthorization

if TYPE_CHECKING:
    from retailtwin_api.demo_runtime.services.twin import TwinService


@dataclass
class ExecutorResult:
    """Result of executing one action."""
    action_type: str
    slot_id: str
    success: bool
    version_before: str
    version_after: str
    error: str | None = None


class ExecutorAgent:
    """Guarded executor — the sole mutation path for the Live Twin.

    The Executor never mutates the Twin directly. It requires a valid,
    non-expired CommitAuthorization from the DCG.
    """

    def __init__(self, twin: TwinService) -> None:
        self._twin = twin
        self._lock = threading.Lock()
        self._audit: list[ExecutorResult] = []

    @property
    def audit_log(self) -> list[ExecutorResult]:
        """Audit trail of all executed actions."""
        with self._lock:
            return list(self._audit)

    def execute(
        self, auth: CommitAuthorization, dcg_validate_fn: Callable[[CommitAuthorization], bool]
    ) -> list[ExecutorResult]:
        """Execute authorized actions on the Live Twin.

        Args:
            auth: DCG-issued CommitAuthorization
            dcg_validate_fn: callable to validate authorization (pass DCG.validate_authorization)

        Returns:
            List of ExecutorResult, one per action.

        Raises:
            ValueError: if authorization is invalid or expired.
        """
        # Validate authorization
        if not dcg_validate_fn(auth):
            raise ValueError(
                f"Authorization {auth.decision_id} is invalid or expired. "
                f"Issued: {auth.issued_at}, Expires: {auth.expires_at}"
            )

        with self._lock:
            results: list[ExecutorResult] = []
            for action in auth.actions:
                result = self._execute_one(action)
                results.append(result)
                self._audit.append(result)

            return results

    def _execute_one(self, action: dict) -> ExecutorResult:
        """Execute a single action. Must hold lock."""
        atype = action.get("action_type", "")
        slot_id = action.get("slot_id", "")
        version_before = self._twin.get_version()

        try:
            if atype == "facings":
                self._twin.apply_facings(slot_id, action.get("facings", 0))
            elif atype == "replenish":
                self._twin.apply_replenish(slot_id, action.get("quantity", 0))
            elif atype == "move":
                self._twin.apply_move(
                    action.get("from_slot_id", ""),
                    action.get("to_slot_id", ""),
                    action.get("quantity", 0),
                )
            else:
                return ExecutorResult(
                    action_type=atype,
                    slot_id=slot_id,
                    success=False,
                    version_before=version_before,
                    version_after=version_before,
                    error=f"Unknown action_type: {atype}",
                )
        except KeyError as e:
            return ExecutorResult(
                action_type=atype,
                slot_id=slot_id,
                success=False,
                version_before=version_before,
                version_after=version_before,
                error=str(e),
            )
        except Exception as e:
            return ExecutorResult(
                action_type=atype,
                slot_id=slot_id,
                success=False,
                version_before=version_before,
                version_after=version_before,
                error=f"Unexpected error: {e}",
            )

        return ExecutorResult(
            action_type=atype,
            slot_id=slot_id,
            success=True,
            version_before=version_before,
            version_after=self._twin.get_version(),
        )
