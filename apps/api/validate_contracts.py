from datetime import datetime, timezone
from retailtwin_api.contracts import Decision, EvidenceBundle, EvidenceItem
from typing import List

def validate_example():
    print("Validating example decision...")
    try:
        # Create a mock EvidenceBundle
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
            items=[EvidenceItem(event_type="test", payload={"foo": "bar"})]
        )

        # Valid decision
        decision = Decision(
            decision_id="d1",
            agent_id="a1",
            context_version="v1",
            context_timestamp=datetime.now(timezone.utc),
            evidence=[bundle],
            proposed_actions=[],
            expected_impact={"kpi_score": 100.0, "description": "test"},
        )
        print("Success: Decision is valid.")
        return True
    except Exception as e:
        print(f"Error: Decision validation failed: {e}")
        return False

if __name__ == "__main__":
    validate_example()
