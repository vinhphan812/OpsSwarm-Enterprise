"""Provider-neutral simulation, candidate, KPI, and agent activity DTOs."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from retailtwin_api.contracts import ActionUnion, ControlStage, DCGVerdictResult
from retailtwin_api.schemas import StoreResponse

SimulationStatus = Literal["pending", "evaluated", "committed", "rejected"]


class SimulationState(BaseModel):
    """A proposed Store Twin snapshot. It is never canonical Live state."""

    model_config = ConfigDict(extra="forbid")

    store: StoreResponse
    context_version: str = Field(min_length=1)


class SimulationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_id: str = Field(min_length=1)
    store_id: str = Field(min_length=1)
    base_context_version: str = Field(min_length=1)
    status: SimulationStatus
    created_at: datetime
    updated_at: datetime
    provenance: str = Field(min_length=1)


class SimulationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulations: list[SimulationSummary]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]
    next_cursor: str | None = None


class SimulationDetail(SimulationSummary):
    actions: list[ActionUnion]
    state: SimulationState
    correlation_id: str | None = Field(default=None, min_length=1)
    agent_id: str | None = Field(default=None, min_length=1)


class CandidateKPI(BaseModel):
    """An evaluator-produced KPI. The API never fabricates its value."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    source: str = Field(min_length=1)


class SimulationCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    simulation_id: str = Field(min_length=1)
    proposed_actions: list[ActionUnion]
    state: SimulationState
    kpis: list[CandidateKPI]
    evaluator_version: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    created_at: datetime


class CandidateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[SimulationCandidateResponse]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]
    next_cursor: str | None = None


class AgentActivityEntry(BaseModel):
    """A safe, polling-friendly lifecycle event; no model reasoning is exposed."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    ts: datetime
    stage: ControlStage
    status: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    decision: str | None = Field(default=None, min_length=1)
    simulation_id: str | None = Field(default=None, min_length=1)
    action_id: str | None = Field(default=None, min_length=1)
    sku: str | None = Field(default=None, min_length=1)
    shelf_id: str | None = Field(default=None, min_length=1)
    slot_id: str | None = Field(default=None, min_length=1)
    focus: str | None = Field(default=None, min_length=1)
    summary: str | None = Field(default=None)


class AgentEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[AgentActivityEntry]
    cursor: str | None


class PageParameters(BaseModel):
    """Explicit validation at the service boundary, reusable without FastAPI."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class SimulationFilters(PageParameters):
    status: SimulationStatus | Literal["open"] | None = None
    store_id: str | None = Field(default=None, min_length=1)

    @field_validator("store_id", mode="before")
    @classmethod
    def strip_store_id(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CursorParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    since: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=50, ge=1, le=100)


# ─── Simulation review (approve / reject) ──────────────────────────────────────


class DecisionReviewVerdict(str, Enum):
    """DCG guard verdict for simulation review."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REFRESH_REQUIRED = "REFRESH_REQUIRED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class DecisionReviewReasonCode(str, Enum):
    """Machine-readable reason code returned after DCG evaluation."""

    APPROVED = "APPROVED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    VERSION_STALE = "VERSION_STALE"
    SIMULATION_NOT_OPEN = "SIMULATION_NOT_OPEN"
    SIMULATION_NOT_FOUND = "SIMULATION_NOT_FOUND"
    DCG_DENY = "DCG_DENY"
    DCG_HUMAN_REVIEW = "DCG_HUMAN_REVIEW"
    DECISION_UNAVAILABLE = "DECISION_UNAVAILABLE"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class SimulationReviewRequest(BaseModel):
    """Request body for POST /simulations/{id}/approve and /reject."""

    model_config = ConfigDict(extra="forbid")

    base_context_version: str = Field(min_length=1)
    proposal_context_version: str = Field(min_length=1)


class SimulationReviewResponse(BaseModel):
    """Response body for simulation approve/reject routes."""

    simulation_id: str
    decision: Literal["approved", "rejected"]
    status: SimulationStatus
    verdict: DecisionReviewVerdict
    reason_code: DecisionReviewReasonCode
    live_context_version: str
    # The guard or Executor code behind ``reason_code`` (e.g. VERSION_STALE, TOKEN_REUSED).
    detail_code: str | None = None
    # The Decision Context Guard result with its per-gate checks, when the guard ran.
    guard: DCGVerdictResult | None = None


class ReviewAuditRecord(BaseModel):
    """Immutable audit trail for each review decision."""

    simulation_id: str
    decision: Literal["approved", "rejected"]
    base_context_version: str
    proposal_context_version: str
    live_context_version: str
    verdict: DecisionReviewVerdict
    reason_code: DecisionReviewReasonCode
    recorded_at: datetime
