"""Provider-neutral simulation, candidate, KPI, and agent activity DTOs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from retailtwin_api.contracts import ActionUnion, ControlStage
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
