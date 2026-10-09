import pytest
from pydantic import ValidationError
from datetime import datetime, timezone
from retailtwin_api.contracts import Decision, EvidenceBundle, MoveProduct, ExpectedImpact

def test_decision_validation():
    # Valid decision
    decision = Decision(
        decision_id="d1",
        agent_id="a1",
        context_version="v1",
        context_timestamp=datetime.now(timezone.utc),
        evidence=[],
        proposed_actions=[MoveProduct(sku="s1", from_slot="a1", to_slot="b1")],
        expected_impact=ExpectedImpact(kpi_score=100.0, description="test"),
    )
    assert decision.decision_id == "d1"

def test_decision_negative_missing_field():
    # Negative test: missing required fields
    with pytest.raises(ValidationError):
        Decision(
            decision_id="d1",
            # missing agent_id
            context_version="v1",
            context_timestamp=datetime.now(timezone.utc),
            evidence=[],
            proposed_actions=[],
            # expected_impact is missing
        )

def test_evidence_bundle_invalid_items():
    # Negative test: invalid items
    with pytest.raises(ValidationError):
        EvidenceBundle(
            bundle_id="b1",
            provenance="test",
            source="test",
            entity_versions={},
            collected_at=datetime.now(timezone.utc),
            freshness=datetime.now(timezone.utc),
            store_id="s1",
            correlation_id="c1",
            is_sufficient=True,
            items="not-a-list-of-items"
        )
