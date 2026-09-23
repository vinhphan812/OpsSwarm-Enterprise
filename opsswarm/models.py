from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


class InvalidStateTransition(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: RunState | None, to_state: RunState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid state transition: {from_state} -> {to_state}")


class RunState(str, Enum):
    OPEN = "OPEN"
    TRIAGE = "TRIAGE"
    INVESTIGATING = "INVESTIGATING"
    DIAGNOSED = "DIAGNOSED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_DECISION = "WAITING_DECISION"
    WAITING_INPUT = "WAITING_INPUT"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


# Valid monotonic state transitions
# None key represents the initial state (before any transition)
VALID_TRANSITIONS: dict[RunState | None, set[RunState]] = {
    None: {RunState.OPEN, RunState.TRIAGE},
    RunState.OPEN: {RunState.TRIAGE},
    RunState.TRIAGE: {RunState.INVESTIGATING, RunState.FAILED, RunState.ABORTED},
    RunState.INVESTIGATING: {RunState.DIAGNOSED, RunState.WAITING_INPUT, RunState.FAILED, RunState.ABORTED},
    RunState.DIAGNOSED: {RunState.PLANNING, RunState.WAITING_INPUT, RunState.FAILED, RunState.ABORTED},
    RunState.PLANNING: {RunState.EXECUTING, RunState.WAITING_APPROVAL, RunState.WAITING_DECISION,
                        RunState.WAITING_INPUT, RunState.FAILED, RunState.ABORTED},
    RunState.EXECUTING: {RunState.VERIFYING, RunState.WAITING_DECISION, RunState.FAILED, RunState.ABORTED},
    RunState.VERIFYING: {RunState.RESOLVED, RunState.FAILED, RunState.ABORTED},
    RunState.WAITING_APPROVAL: {RunState.PLANNING, RunState.EXECUTING, RunState.ABORTED},
    RunState.WAITING_DECISION: {RunState.PLANNING, RunState.EXECUTING, RunState.INVESTIGATING, RunState.ABORTED},
    RunState.WAITING_INPUT: {RunState.DIAGNOSED, RunState.INVESTIGATING, RunState.ABORTED},
    RunState.RESOLVED: set(),  # Terminal - no transitions out
    RunState.FAILED: {RunState.WAITING_APPROVAL, RunState.WAITING_DECISION, RunState.WAITING_INPUT,
                      RunState.INVESTIGATING, RunState.ABORTED},
    RunState.ABORTED: set(),  # Terminal - no transitions out
}

# Terminal states - no further transitions allowed
TERMINAL_STATES: set[RunState] = {RunState.RESOLVED, RunState.FAILED, RunState.ABORTED}


class Risk(str, Enum):
    READ = "read"
    SAFE_WRITE = "safe_write"
    RISKY_WRITE = "risky_write"
    DESTRUCTIVE = "destructive"


class CheckpointType(str, Enum):
    """Checkpoint types for crash recovery (ADR-009-3)."""
    STATE_TRANSITION = "state_transition"
    HUMAN_GATE = "human_gate"
    EXECUTION = "execution"


class CommandOutcome(str, Enum):
    """Command execution outcome for durable state tracking (ADR-012, Issue #9 fix).

    Distinguishes between:
    - RECEIVED: Command received, execution not yet attempted
    - EXECUTING: Command execution in progress
    - CONFIRMED: Command verified externally (S7 evidence or reconciliation)
    - ABSENT: Command provably not executed or failed
    - UNKNOWN: Command may have executed but outcome unconfirmed (requires reconciliation)
    """
    RECEIVED = "received"
    EXECUTING = "executing"
    CONFIRMED = "confirmed"
    ABSENT = "absent"
    UNKNOWN = "unknown"

    @classmethod
    def from_legacy(cls, value: str) -> CommandOutcome:
        """Map legacy values for backward compatibility."""
        mapping = {
            "received": cls.RECEIVED,
            "executing": cls.EXECUTING,
            "executed": cls.CONFIRMED,
            "failed": cls.ABSENT,
            "reconciled": cls.CONFIRMED,
        }
        return mapping.get(value, cls.UNKNOWN)


class TaskType(str, Enum):
    OBSERVE = "OBSERVE"
    INVESTIGATE = "INVESTIGATE"
    DIAGNOSE = "DIAGNOSE"
    REMEDIATE = "REMEDIATE"
    VERIFY = "VERIFY"


class IncidentContext(BaseModel):
    issue_number: int
    title: str
    body: str = ""
    service: str = "unknown"
    environment: str = "unknown"
    severity: str = "UNKNOWN"
    symptoms: list[str] = Field(default_factory=list)
    customer_impact: str = "unknown"
    source: str = "github"
    actor: str | None = None
    labels: list[str] = Field(default_factory=list)


class Task(BaseModel):
    id: str
    type: TaskType
    objective: str
    profile: str
    required_capabilities: list[str] = Field(default_factory=list)
    risk: Risk = Risk.READ
    depends_on: list[str] = Field(default_factory=list)
    parallelizable: bool = True
    expected_output: str = "Finding"
    status: Literal["PENDING", "RUNNING", "DONE", "FAILED", "SKIPPED"] = "PENDING"


class Finding(BaseModel):
    task_id: str
    finding: str
    evidence: list[str] = Field(default_factory=list)
    hypothesis: str | None = None
    confidence: float = 0.0
    recommended_next_action: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class RootCauseArtifact(BaseModel):
    status: Literal["confirmed", "uncertain"] = "uncertain"
    proximate_cause: str = "unknown"
    root_cause: str = "unknown"
    causal_chain: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    remediation_options: list[str] = Field(default_factory=list)
    human_input_question: str | None = None
    corrective_actions: list[str] = Field(default_factory=list)


class RemediationOption(BaseModel):
    id: str
    description: str
    profile: str = "recovery-responder"
    risk: Risk
    estimated_recovery: str | None = None
    rationale: str = ""
    capabilities: list[str] = Field(default_factory=list)


class RecoveryPlan(BaseModel):
    options: list[RemediationOption]
    recommended_option: str | None = None
    confidence: float = 0.0
    requires_business_input: bool = False
    business_input_question: str | None = None


class DecisionRequest(BaseModel):
    id: str
    kind: Literal["APPROVAL", "DECISION", "INPUT"]
    reason: str
    options: list[RemediationOption] = Field(default_factory=list)
    recommended_option: str | None = None
    question: str | None = None
    status: Literal["OPEN", "ANSWERED", "REJECTED", "ABORTED"] = "OPEN"


class ExecutionResult(BaseModel):
    option_id: str
    success: bool
    summary: str
    evidence: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    verified: bool
    summary: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw: dict[str, Any] = Field(default_factory=dict)
    # S7 veto: if True, abort instead of fail on verification failure
    abort: bool = False


class RunRecord(BaseModel):
    run_id: str
    issue_number: int
    state: RunState = RunState.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    incident: IncidentContext | None = None
    tasks: list[Task] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    root_cause: RootCauseArtifact | None = None
    recovery_plan: RecoveryPlan | None = None
    decision: DecisionRequest | None = None
    execution: ExecutionResult | None = None
    verification: VerificationResult | None = None
    human_inputs: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    # Checkpoint fields for run recovery (ADR-009-3)
    checkpoint_state: str | None = None
    last_checkpoint_at: datetime | None = None
    checkpoint_sequence: int = 0
    # Evidence deduplication fields (ADR-009-4)
    evidence_keys: set[str] = Field(default_factory=set)
    # State enforcement mode (ADR-009-5)
    state_enforcement: str = "audit"  # "audit", "strict", or "disabled"
    # Idempotency fields for webhook/command deduplication (ADR-009-1)
    idempotency_keys: set[str] = Field(default_factory=set)  # GitHub delivery/comment IDs
    # Command execution tracking (Issue #9 fix): comment_id -> CommandOutcome
    # This enables durable state tracking across crash windows
    command_outcomes: dict[str, str] = Field(default_factory=dict)
    # Legacy field: kept for backward compatibility, migrated to command_outcomes
    executed_commands: set[str] = Field(default_factory=set)

    # --- Command outcome helpers (Issue #9 fix) ---

    def mark_command_received(self, comment_id: str) -> None:
        """Mark a command as received (not yet executed)."""
        self.command_outcomes[comment_id] = CommandOutcome.RECEIVED.value

    def mark_command_executing(self, comment_id: str) -> None:
        """Mark a command as currently executing."""
        self.command_outcomes[comment_id] = CommandOutcome.EXECUTING.value

    def mark_command_confirmed(self, comment_id: str) -> None:
        """Mark a command as successfully executed."""
        self.command_outcomes[comment_id] = CommandOutcome.CONFIRMED.value
        # Also add to legacy field for backward compatibility
        self.executed_commands.add(comment_id)

    def mark_command_absent(self, comment_id: str) -> None:
        """Mark a command as failed (absent)."""
        self.command_outcomes[comment_id] = CommandOutcome.ABSENT.value

    def mark_command_unknown(self, comment_id: str) -> None:
        """Mark a command as unknown (crash window)."""
        self.command_outcomes[comment_id] = CommandOutcome.UNKNOWN.value

    def is_command_confirmed(self, comment_id: str) -> bool:
        """Check if a command has been confirmed."""
        return self.command_outcomes.get(comment_id) == CommandOutcome.CONFIRMED.value

    def is_command_received(self, comment_id: str) -> bool:
        """Check if a command has been received (at any outcome state)."""
        return comment_id in self.command_outcomes

    def get_command_outcome(self, comment_id: str) -> str | None:
        """Get the current outcome state of a command."""
        return self.command_outcomes.get(comment_id)

    def get_pending_commands(self) -> list[str]:
        """Get list of commands that are received but not yet executed."""
        return [
            cmd_id for cmd_id, outcome in self.command_outcomes.items()
            if outcome in (CommandOutcome.RECEIVED.value, CommandOutcome.EXECUTING.value)
        ]

    def transition(self, new_state: RunState, enforcement: str = "audit") -> None:
        """Transition to a new state with optional validation.

        Args:
            new_state: The target state to transition to.
            enforcement: Validation mode - "audit" (log warning, allow), "strict" (raise), or "disabled" (skip).

        Raises:
            InvalidStateTransition: If enforcement is "strict" and the transition is invalid.
        """
        # Disabled mode: skip all validation
        if enforcement == "disabled":
            self.state = new_state
            self.updated_at = utc_now()
            return

        # Check terminal state first
        if self.state in TERMINAL_STATES:
            error_msg = f"Cannot transition from terminal state {self.state.value}"
            if enforcement == "strict":
                raise InvalidStateTransition(self.state, new_state)
            # Audit mode: log warning but allow transition for backward compatibility
            logger.warning(f"[AUDIT] {error_msg} (enforcement={enforcement})")
            self.state = new_state
            self.updated_at = utc_now()
            return

        # Check if transition is valid
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            error_msg = f"Invalid transition {self.state.value} -> {new_state.value}. Allowed: {[s.value for s in allowed]}"
            if enforcement == "strict":
                raise InvalidStateTransition(self.state, new_state)
            # Audit mode: log warning but allow transition for backward compatibility
            logger.warning(f"[AUDIT] {error_msg} (enforcement={enforcement})")

        self.state = new_state
        self.updated_at = utc_now()

    def can_transition_to(self, new_state: RunState) -> bool:
        """Check if a transition to the given state is valid without performing it."""
        if self.state in TERMINAL_STATES:
            return False
        return new_state in VALID_TRANSITIONS.get(self.state, set())
