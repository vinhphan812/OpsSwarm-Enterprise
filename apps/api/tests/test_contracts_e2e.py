from datetime import datetime, timezone
from retailtwin_api.contracts import Decision, ControlStage, ToolCapability, MoveProduct, EvidenceBundle, EvidenceItem
import pytest

def test_contracts_e2e_state_machine():
    # Test valid Decision creation
    bundle = EvidenceBundle(
        bundle_id="b1",
        provenance="test",
        source="test",
        entity_versions={"v1": "1.0"},
        collected_at=datetime.now(timezone.utc),
        freshness=datetime.now(timezone.utc),
        store_id="s1",
        correlation_id="c1",
        is_sufficient=True,
        items=[EvidenceItem(event_type="test", payload={"key": "value"})]
    )

    action = MoveProduct(sku="s1", from_slot="a1", to_slot="b1")

    decision = Decision(
        decision_id="d1",
        agent_id="a1",
        context_version="v1",
        context_timestamp=datetime.now(timezone.utc),
        evidence=[bundle],
        proposed_actions=[action],
        expected_impact={"kpi_score": 100.0, "description": "test"}
    )

    assert decision.decision_id == "d1"
    assert len(decision.evidence) == 1
    assert decision.evidence[0].bundle_id == "b1"
    assert len(decision.proposed_actions) == 1
    assert isinstance(decision.proposed_actions[0], MoveProduct)
