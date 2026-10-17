from typing import List, Optional, Any, Union, Dict
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime, timezone

# 1. ControlStage
class ControlStage(str, Enum):
    OBSERVE = "OBSERVE"
    DETECT = "DETECT"
    INVESTIGATE = "INVESTIGATE"
    PLAN = "PLAN"
    SIMULATE = "SIMULATE"
    GUARD = "GUARD"
    ACT = "ACT"
    VERIFY = "VERIFY"

# 2. ToolCapability
class ToolCapability(str, Enum):
    READ = "READ"
    SIMULATION = "SIMULATION"
    COMMIT_REQUEST = "COMMIT_REQUEST"

# 3. Actions
class MoveProduct(BaseModel):
    sku: str
    from_slot: str
    to_slot: str

class ChangeFacings(BaseModel):
    sku: str
    facings: int = Field(..., ge=1, le=100)

class ReplenishShelf(BaseModel):
    sku: str
    quantity: int = Field(..., ge=1, le=1000)

ActionUnion = Union[MoveProduct, ChangeFacings, ReplenishShelf]

# 4. Evidence
class EvidenceItem(BaseModel): # Inferred requirement
    event_type: str
    payload: Dict[str, Any]

class EvidenceBundle(BaseModel):
    bundle_id: str
    provenance: str
    source: str
    entity_versions: Dict[str, str]
    # Demand-evidence versions keyed by source name (issue #215 /
    # ADR 0024). ``sales_history`` carries the BigQuery job id;
    # ``forecast`` carries the deterministic forecast formula id. The
    # KPI evaluator reads ``sales_history`` (or whichever source the
    # chain maps to demand evidence) and threads it into
    # ``evaluator_version`` on every scored candidate. Empty when no
    # demand evidence source succeeded.
    source_versions: Dict[str, str] = {}
    collected_at: datetime
    freshness: datetime
    store_id: str
    correlation_id: str
    is_sufficient: bool
    items: List[EvidenceItem] = []

# 5. Decision
class ExpectedImpact(BaseModel):
    kpi_score: float
    description: str

class Decision(BaseModel):
    decision_id: str
    agent_id: str
    context_version: str
    context_timestamp: datetime
    evidence: List[EvidenceBundle]
    proposed_actions: List[ActionUnion]
    simulation_id: Optional[str] = None
    expected_impact: ExpectedImpact

# 6. Simulation
class SimulationRequest(BaseModel):
    simulation_id: str
    actions: List[ActionUnion]

class SimulationCandidate(BaseModel):
    candidate_id: str
    simulation_id: str
    proposed_actions: List[ActionUnion]

class SimulationKPIResult(BaseModel):
    simulation_id: str
    kpi_score: float
    duration_ms: int
    # Version of the demand evidence the candidate was scored against
    # (issue #215 / ADR 0024). Threaded from the BigQuery-backed
    # ``get_sales_history`` reader via the canonical KPI evaluator
    # (``services/simulation/kpi/evaluator.py``). ``"none"`` when no
    # demand evidence was threaded (historic callers).
    evaluator_version: str = "none"

# 7. DCG
class DCGVerdict(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REFRESH_REQUIRED = "REFRESH_REQUIRED"
    HUMAN_REVIEW = "HUMAN_REVIEW"

class DCGVerdictResult(BaseModel):
    verdict: DCGVerdict
    reason_code: str
    context_version: str
    context_hash: str
    expiry: datetime
    policy_result: Dict[str, Any]

# 8. Commit
class CommitAuthorization(BaseModel):
    decision_id: str
    context_hash: str
    actions: List[ActionUnion]
    expiry: datetime

# 9. Executor/Verifier
class ExecutorResult(BaseModel):
    action_id: str
    status: str
    error: Optional[str]

class VerifierOutcome(BaseModel):
    action_id: str
    verified: bool
    reason: Optional[str]

# 10. Bounded Error/Retry
class RetryPhase(str, Enum):
    OBSERVATION = "OBSERVATION"
    SIMULATION = "SIMULATION"
    EXECUTION = "EXECUTION"

class RetryPolicy(BaseModel):
    phase: RetryPhase
    max_retries: int
    error_code: str
