from typing import List, Optional, Any, Union
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
from retailtwin_api.schemas import StoreEvent

class ActionType(str, Enum):
    CANDIDATE = "candidate"
    LIVE = "live"

class Action(BaseModel):
    action_id: str
    type: ActionType
    payload: Any

class EvidenceBundle(BaseModel):
    bundle_id: str
    events: List[StoreEvent]

class Decision(BaseModel):
    decision_id: str
    agent_id: str
    context_version: str
    context_timestamp: datetime
    evidence: List[Any]
    proposed_actions: List[Action]
    simulation_id: Optional[str] = None
    expected_impact: dict[str, Any]

class SimulationResult(BaseModel):
    simulation_id: str
    outcome: str
    data: Any

class DCGOutcome(BaseModel):
    decision_id: str
    authorized: bool
    reason: Optional[str] = None
