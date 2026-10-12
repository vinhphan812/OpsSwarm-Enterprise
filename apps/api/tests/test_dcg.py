"""Unit tests for DCG (Decision Context Guard)."""
import pytest
from datetime import datetime, timedelta, timezone
from retailtwin_api.demo_runtime.guard.decision_context_guard import (
    CommitAuthorization,
    DCG,
    DCGVerdict,
    Decision,
)
from retailtwin_api.demo_runtime.services.twin import TwinService


FIXTURES = [
    {"slot_id": "s01", "sku": "P001", "facings": 4, "shelf_quantity": 20, "backroom_quantity": 50},
    {"slot_id": "s02", "sku": "P017", "facings": 3, "shelf_quantity": 12, "backroom_quantity": 35},
]


def _make_decision(context_version: str, age_seconds: float = 0, decision_id: str = "dec-001") -> Decision:
    return Decision(
        decision_id=decision_id,
        context_version=context_version,
        context_timestamp=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        proposed_actions=[
            {"action_type": "facings", "slot_id": "s01", "facings": 7}
        ],
    )


class TestDCG:
    def test_allow_valid_decision(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = _make_decision(twin.get_context_version(), age_seconds=5)
        result = dcg.validate(decision)
        assert result.verdict == DCGVerdict.ALLOW
        assert result.errors == []

    def test_deny_empty_decision_id(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = _make_decision(twin.get_context_version(), decision_id="")
        result = dcg.validate(decision)
        assert result.verdict == DCGVerdict.DENY
        assert any("decision_id" in e for e in result.errors)

    def test_refresh_required_stale_context(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        cv = twin.get_context_version()
        # Reset to change context
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = _make_decision(cv)  # old context version
        result = dcg.validate(decision)
        assert result.verdict in (DCGVerdict.REFRESH_REQUIRED, DCGVerdict.DENY)

    def test_deny_stale_timestamp(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        # 120 seconds old — exceeds 60s freshness window
        decision = _make_decision(twin.get_context_version(), age_seconds=120)
        result = dcg.validate(decision)
        assert result.verdict in (DCGVerdict.REFRESH_REQUIRED, DCGVerdict.DENY)
        assert any("stale" in e or "age" in e for e in result.errors)

    def test_deny_unknown_action_type(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = Decision(
            decision_id="dec-001",
            context_version=twin.get_context_version(),
            context_timestamp=datetime.now(timezone.utc),
            proposed_actions=[
                {"action_type": "unknown_action", "slot_id": "s01"}
            ],
        )
        result = dcg.validate(decision)
        assert result.verdict == DCGVerdict.DENY
        assert any("action_type" in e for e in result.errors)

    def test_deny_missing_slot(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = Decision(
            decision_id="dec-001",
            context_version=twin.get_context_version(),
            context_timestamp=datetime.now(timezone.utc),
            proposed_actions=[
                {"action_type": "facings", "slot_id": "nonexistent", "facings": 5}
            ],
        )
        result = dcg.validate(decision)
        assert result.verdict == DCGVerdict.DENY
        assert any("not found" in e for e in result.errors)

    def test_authorize_returns_auth_for_valid_decision(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = _make_decision(twin.get_context_version(), age_seconds=5)
        auth = dcg.authorize(decision)
        assert auth is not None
        assert auth.decision_id == "dec-001"
        assert auth.is_valid()

    def test_authorize_returns_none_for_invalid_decision(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = _make_decision(twin.get_context_version(), age_seconds=120)
        auth = dcg.authorize(decision)
        assert auth is None

    def test_validate_authorization_valid(self):
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        dcg = DCG(twin)
        decision = _make_decision(twin.get_context_version(), age_seconds=5)
        auth = dcg.authorize(decision)
        assert auth is not None
        assert dcg.validate_authorization(auth)

    def test_stale_context_blocked(self):
        """G04 gate: stale decision cannot pass DCG."""
        twin = TwinService("store-001")
        twin.reset(FIXTURES)
        old_cv = twin.get_context_version()
        old_ts = datetime.now(timezone.utc)
        # Reset creates new context
        twin.reset(FIXTURES)
        # New decision from new context
        decision = Decision(
            decision_id="dec-stale",
            context_version=old_cv,  # stale version
            context_timestamp=old_ts,  # stale timestamp
            proposed_actions=[
                {"action_type": "facings", "slot_id": "s01", "facings": 5}
            ],
        )
        dcg = DCG(twin)
        result = dcg.validate(decision)
        assert result.verdict != DCGVerdict.ALLOW, "Stale decision must be blocked"
