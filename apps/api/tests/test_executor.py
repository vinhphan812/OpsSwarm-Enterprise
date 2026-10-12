"""Unit tests for ExecutorAgent."""
import pytest
from datetime import datetime, timedelta, timezone
from retailtwin_api.demo_runtime.agents.executor import ExecutorAgent
from retailtwin_api.demo_runtime.guard.decision_context_guard import CommitAuthorization
from retailtwin_api.demo_runtime.services.twin import TwinService

FIXTURES = [
    {"slot_id": "s01", "sku": "P001", "facings": 4, "shelf_quantity": 20, "backroom_quantity": 50},
    {"slot_id": "s02", "sku": "P017", "facings": 3, "shelf_quantity": 12, "backroom_quantity": 35},
]


def _make_auth(decision_id: str, actions: list, expires_in: float = 60) -> CommitAuthorization:
    now = datetime.now(timezone.utc)
    return CommitAuthorization(
        decision_id=decision_id,
        actions=actions,
        issued_at=now,
        expires_at=now + timedelta(seconds=expires_in),
    )


class TestExecutorAgent:
    def test_execute_facings_action(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-001", [{"action_type": "facings", "slot_id": "s01", "facings": 8}])
        results = exec_.execute(auth, lambda a: True)
        assert len(results) == 1
        assert results[0].success
        assert twin.read_slot("s01").facings == 8

    def test_execute_replenish_action(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-002", [{"action_type": "replenish", "slot_id": "s02", "quantity": 10}])
        results = exec_.execute(auth, lambda a: True)
        assert results[0].success
        assert twin.read_slot("s02").shelf_quantity == 22

    def test_execute_move_action(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-003", [{"action_type": "move", "from_slot_id": "s01", "to_slot_id": "s02", "quantity": 5}])
        results = exec_.execute(auth, lambda a: True)
        assert results[0].success
        assert twin.read_slot("s01").shelf_quantity == 15
        assert twin.read_slot("s02").shelf_quantity == 17

    def test_execute_requires_valid_auth(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-004", [{"action_type": "facings", "slot_id": "s01", "facings": 9}])
        # Simulate expired auth
        with pytest.raises(ValueError, match="invalid or expired"):
            exec_.execute(auth, lambda a: False)

    def test_execute_unknown_action_type(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-005", [{"action_type": "unknown", "slot_id": "s01"}])
        results = exec_.execute(auth, lambda a: True)
        assert not results[0].success
        assert "Unknown action_type" in results[0].error

    def test_execute_nonexistent_slot(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-006", [{"action_type": "facings", "slot_id": "nonexistent", "facings": 5}])
        results = exec_.execute(auth, lambda a: True)
        assert not results[0].success

    def test_audit_log(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-007", [{"action_type": "facings", "slot_id": "s01", "facings": 6}])
        exec_.execute(auth, lambda a: True)
        assert len(exec_.audit_log) == 1
        assert exec_.audit_log[0].success

    def test_version_increments_on_execute(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        exec_ = ExecutorAgent(twin)
        auth = _make_auth("dec-008", [{"action_type": "facings", "slot_id": "s01", "facings": 7}])
        exec_.execute(auth, lambda a: True)
        assert twin.get_version() == "1"
