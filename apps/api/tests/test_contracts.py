import pytest
from pydantic import ValidationError
from datetime import datetime
from retailtwin_api.contracts import Decision, EvidenceBundle, Action, ActionType, SimulationResult
from retailtwin_api.schemas import StoreEvent

def test_decision_validation():
    # Valid decision
    decision = Decision(
        decision_id="d1",
        agent_id="a1",
        context_version="v1",
        context_timestamp=datetime.now(),
        evidence=[],
        proposed_actions=[Action(action_id="act1", type=ActionType.CANDIDATE, payload={"foo": "bar"})],
        expected_impact={}
    )
    assert decision.decision_id == "d1"

def test_decision_negative_missing_field():
    # Negative test: missing required fields
    with pytest.raises(ValidationError):
        Decision(
            decision_id="d1",
            # missing agent_id
            context_version="v1",
            context_timestamp=datetime.now(),
            evidence=[],
            proposed_actions=[],
            expected_impact={}
        )

def test_evidence_bundle_invalid_events():
    # Negative test: invalid events
    with pytest.raises(ValidationError):
        EvidenceBundle(bundle_id="b1", events=["not-a-store-event"])

def test_simulation_result_validation():
    result = SimulationResult(simulation_id="s1", outcome="success", data={"score": 100})
    assert result.simulation_id == "s1"
    assert result.outcome == "success"
