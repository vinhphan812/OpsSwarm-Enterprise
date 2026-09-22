from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


class Risk(str, Enum):
    READ = "read"
    SAFE_WRITE = "safe_write"
    RISKY_WRITE = "risky_write"
    DESTRUCTIVE = "destructive"


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

    def transition(self, new_state: RunState) -> None:
        self.state = new_state
        self.updated_at = utc_now()
