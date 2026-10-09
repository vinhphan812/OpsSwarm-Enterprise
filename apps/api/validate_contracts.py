from datetime import datetime
from retailtwin_api.contracts import Decision, Action, ActionType
from retailtwin_api.schemas import StoreEvent
import pytz

def validate_example():
    print("Validating example decision...")
    try:
        # Create a mock StoreEvent
        event = StoreEvent(
            event_id="e1",
            correlation_id="c1",
            event_type="test",
            store_id="s1",
            sku="sku1",
            quantity=1,
            occurred_at=datetime.now(pytz.utc),
            source="test-source"
        )

        # Valid decision
        decision = Decision(
            decision_id="d1",
            agent_id="a1",
            context_version="v1",
            context_timestamp=datetime.now(),
            evidence=[event],
            proposed_actions=[Action(action_id="act1", type=ActionType.CANDIDATE, payload={"foo": "bar"})],
            expected_impact={"score": 100}
        )
        print("Success: Decision is valid.")
        return True
    except Exception as e:
        print(f"Error: Decision validation failed: {e}")
        return False

if __name__ == "__main__":
    validate_example()
