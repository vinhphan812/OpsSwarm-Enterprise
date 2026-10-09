# Technical Specification: RetailTwin API Contracts

This specification defines the authoritative Pydantic models for the RetailTwin API, ensuring type safety and contract adherence for all agents and services.

## Phase 1: Core Contracts

### 1. ControlStage Enum
```python
class ControlStage(str, Enum):
    OBSERVE = "OBSERVE"
    DETECT = "DETECT"
    INVESTIGATE = "INVESTIGATE"
    PLAN = "PLAN"
    SIMULATE = "SIMULATE"
    GUARD = "GUARD"
    ACT = "ACT"
    VERIFY = "VERIFY"
```

### 2. ToolCapability Taxonomy
```python
class ToolCapability(str, Enum):
    READ = "READ"
    SIMULATION = "SIMULATION"
    COMMIT_REQUEST = "COMMIT_REQUEST"
```

### 3. Typed Action Contracts
```python
class MoveProduct(BaseModel):
    sku: str
    from_slot: str
    to_slot: str

class ChangeFacings(BaseModel):
    sku: str
    facings: int = Field(..., ge=1, le=100) # Assuming MAX_FACINGS=100

class ReplenishShelf(BaseModel):
    sku: str
    quantity: int = Field(..., ge=1, le=1000) # Assuming MAX_REPLENISH=1000

# Action Union Type
ActionUnion = Union[MoveProduct, ChangeFacings, ReplenishShelf]
```

### 4. EvidenceBundle
```python
class EvidenceBundle(BaseModel):
    bundle_id: str
    provenance: str
    source: str
    entity_versions: dict[str, str]
    collected_at: datetime
    freshness: datetime
    store_id: str
    correlation_id: str
    is_sufficient: bool
```

### 5. Decision
```python
class Decision(BaseModel):
    decision_id: str
    agent_id: str
    context_version: str
    context_timestamp: datetime
    evidence: List[EvidenceBundle]
    proposed_actions: List[ActionUnion]
    simulation_id: Optional[str] = None
    expected_impact: ExpectedImpact # Define ExpectedImpact
```

### 6. Simulation KPI Schema
```python
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
```

### 7. DCGVerdict
```python
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
    policy_result: dict[str, Any]
```

### 8. CommitAuthorization
```python
class CommitAuthorization(BaseModel):
    decision_id: str
    context_hash: str
    actions: List[ActionUnion]
    expiry: datetime
```

### 9. ExecutorResult + VerifierOutcome
```python
class ExecutorResult(BaseModel):
    action_id: str
    status: str
    error: Optional[str]

class VerifierOutcome(BaseModel):
    action_id: str
    verified: bool
    reason: Optional[str]
```

### 10. Bounded Error/Retry States
```python
class RetryPhase(str, Enum):
    OBSERVATION = "OBSERVATION"
    SIMULATION = "SIMULATION"
    EXECUTION = "EXECUTION"

class RetryPolicy(BaseModel):
    phase: RetryPhase
    max_retries: int
    error_code: str
```

## Phase 2: Boundary Invariants

### 11. Capability Boundary
The Planner is strictly limited to reading `Live` state via the `IGuard` interface. It cannot directly mutate `Live` state. All mutations must pass through `CommitAuthorization` after simulation.

### 12-17. Rejection Scenarios
- Illegal Transition: `LEGAL_TRANSITIONS` check fails.
- Stale Context: `context_version` is behind `Live`.
- Insufficient Evidence: `EvidenceBundle.is_sufficient` is False.
- Policy Denied: `DCGVerdict` is `DENY`.
- Execution Failed: `ExecutorResult` includes error.

## Phase 3: Traceability and Maintenance

### 18. State-Machine Trace
Demand-surge trace contract covers: `[Pre-Surge] → [Surge Detected] → [Planner Init] → [Simulation] → [Commit] → [Verification] → [Post-Surge Invariant Check]`.

### 19. Docs Alignment
All files in `docs/` have been audited and updated to match these contracts.

### 20. DateTime Fix
All `datetime` objects must use UTC: `datetime.now(timezone.utc)`.

### 21. CI/Coverage
Contracts under `apps/api/retailtwin_api/contracts.py` must maintain 100% test coverage via `pytest`.

### 22. Validator Fix
`apps/api/validate_contracts.py` has been updated to use `datetime.now(timezone.utc)`.
