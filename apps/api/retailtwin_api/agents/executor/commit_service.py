"""One approval: guard on fresh reads, then a signed authorization, then the guarded Executor."""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from retailtwin_api.agents.executor.executor import CommitOutcome, GuardedExecutor
from retailtwin_api.contracts import DCGVerdict, DCGVerdictResult, Decision
from retailtwin_api.firestore_twin import LiveTwinRepository
from retailtwin_api.guard.decision_context_guard import (
    VERSION_STALE,
    DecisionContextGuard,
    GuardAuditSink,
    GuardPolicy,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.authorization import (
    SIGNING_KEY_ENV,
    CommitAuthorizer,
    InMemoryAuthorizationLedger,
)

log = logging.getLogger(__name__)


class ApprovalOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: DCGVerdict
    reason_code: str
    guard: DCGVerdictResult
    commit: CommitOutcome | None = None

    @property
    def committed(self) -> bool:
        return self.commit is not None and self.commit.committed


class CommitService:
    def __init__(self, gate: NoStaleCommit, authorizer: CommitAuthorizer, executor: GuardedExecutor) -> None:
        self._gate = gate
        self._authorizer = authorizer
        self._executor = executor

    @property
    def can_commit(self) -> bool:
        return self._authorizer.can_issue

    def approve(self, decision: Decision) -> ApprovalOutcome:
        """Commit ``decision`` if the guard allows it now and still allows it at the write.

        Raises ``SigningKeyMissing`` when no authorization can be issued.
        """

        guard, binding = self._gate.authorize(decision)
        if binding is None:
            return ApprovalOutcome(verdict=guard.verdict, reason_code=guard.reason_code, guard=guard)
        token = self._authorizer.issue(decision, binding)
        outcome = self._executor.commit(decision, token)
        if outcome.committed:
            return ApprovalOutcome(verdict=DCGVerdict.ALLOW, reason_code=outcome.reason_code, guard=guard, commit=outcome)
        if outcome.guard is not None and outcome.guard.verdict is not DCGVerdict.ALLOW:
            verdict = outcome.guard.verdict
        elif outcome.reason_code == VERSION_STALE:
            verdict = DCGVerdict.REFRESH_REQUIRED
        else:
            verdict = DCGVerdict.DENY
        return ApprovalOutcome(verdict=verdict, reason_code=outcome.reason_code, guard=outcome.guard or guard, commit=outcome)


def build_commit_service(
    twin: LiveTwinRepository,
    audit: GuardAuditSink,
    *,
    production: bool,
    environ: Mapping[str, str] | None = None,
) -> CommitService:
    """Wire guard, ledger, authorizer and Executor from the environment.

    Outside production a missing signing key is replaced by a random per-process
    key: tokens never leave the process. In production a missing key means no
    authorization is ever issued.
    """

    env = dict(os.environ if environ is None else environ)
    if not env.get(SIGNING_KEY_ENV, "").strip() and not production:
        log.warning("%s is not set; using a per-process commit signing key", SIGNING_KEY_ENV)
        env[SIGNING_KEY_ENV] = secrets.token_hex(32)
    ledger = InMemoryAuthorizationLedger()
    authorizer = CommitAuthorizer.from_env(ledger, env)
    guard = DecisionContextGuard(twin, GuardPolicy.from_env(env))
    gate = NoStaleCommit(guard, audit)
    return CommitService(gate, authorizer, GuardedExecutor(twin, authorizer, gate))
