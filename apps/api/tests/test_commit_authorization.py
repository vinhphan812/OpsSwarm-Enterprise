"""Signed, single-use commit authorization (#18)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from retailtwin_api.contracts import ChangeFacings, Decision, EvidenceBundle, ExpectedImpact, ReplenishShelf
from retailtwin_api.guard.decision_context_guard import CommitBinding, action_hash
from retailtwin_api.guard.decision_context_guard.authorization import (
    ACTION_MISMATCH,
    INVALID_SIGNATURE,
    MISSING_TOKEN,
    SIGNING_KEY_ENV,
    TOKEN_EXPIRED,
    TOKEN_REUSED,
    TOKEN_TTL_ENV,
    UNKNOWN_TOKEN,
    AuthorizationError,
    CommitAuthorizer,
    InMemoryAuthorizationLedger,
    SigningKeyMissing,
)

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
KEY = b"test-signing-key"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def ledger() -> InMemoryAuthorizationLedger:
    return InMemoryAuthorizationLedger()


@pytest.fixture
def authorizer(ledger: InMemoryAuthorizationLedger, clock: Clock) -> CommitAuthorizer:
    return CommitAuthorizer(KEY, ledger, clock=clock)


def make_decision(decision_id: str = "dec-1", quantity: int = 6) -> Decision:
    return Decision(
        decision_id=decision_id,
        agent_id="planner",
        context_version="store-001:v1",
        context_timestamp=T0,
        evidence=[
            EvidenceBundle(
                bundle_id="b1", provenance="tool-registry", source="investigator",
                entity_versions={"P001": "1"}, collected_at=T0, freshness=T0,
                store_id="store-001", correlation_id="corr-1", is_sufficient=True,
            )
        ],
        proposed_actions=[ReplenishShelf(sku="P001", quantity=quantity), ChangeFacings(sku="P001", facings=3)],
        expected_impact=ExpectedImpact(kpi_score=0.2, description="restock"),
    )


def make_binding(decision_id: str = "dec-1", expiry: datetime = T0 + timedelta(minutes=2)) -> CommitBinding:
    return CommitBinding(
        decision_id=decision_id, store_id="store-001", context_hash="hash-1",
        entity_versions={"P001": 1}, expiry=expiry,
    )


def refusal(authorizer: CommitAuthorizer, decision: Decision, token: object) -> str:
    with pytest.raises(AuthorizationError) as caught:
        authorizer.redeem(decision, token)  # type: ignore[arg-type]
    return caught.value.code


def test_valid_token_redeems_once_to_its_binding(authorizer: CommitAuthorizer) -> None:
    decision = make_decision()
    token = authorizer.issue(decision, make_binding())

    assert token.decision_id == "dec-1"
    assert token.action_hashes == tuple(action_hash(a) for a in decision.proposed_actions)
    assert token.entity_versions == {"P001": 1}
    assert token.expiry == T0 + timedelta(seconds=30)
    assert len(token.nonce) == 32 and token.signature
    # The redeemed binding carries the token's shorter expiry.
    assert authorizer.redeem(decision, token) == make_binding(expiry=token.expiry)
    assert refusal(authorizer, decision, token) == TOKEN_REUSED


def test_two_tokens_for_one_decision_have_distinct_nonces(authorizer: CommitAuthorizer) -> None:
    decision = make_decision()
    assert authorizer.issue(decision, make_binding()).nonce != authorizer.issue(decision, make_binding()).nonce


def test_token_never_outlives_its_binding(authorizer: CommitAuthorizer) -> None:
    token = authorizer.issue(make_decision(), make_binding(expiry=T0 + timedelta(seconds=10)))
    assert token.expiry == T0 + timedelta(seconds=10)


def test_missing_token_is_refused(authorizer: CommitAuthorizer) -> None:
    assert refusal(authorizer, make_decision(), None) == MISSING_TOKEN


@pytest.mark.parametrize(
    "change",
    [
        {"entity_versions": {"P001": 2}},
        {"context_hash": "other"},
        {"expiry": T0 + timedelta(hours=1)},
        {"decision_id": "dec-2"},
        {"signature": "0" * 64},
    ],
    ids=["versions", "context-hash", "expiry", "decision", "signature"],
)
def test_tampered_token_is_refused(authorizer: CommitAuthorizer, change: dict[str, object]) -> None:
    decision = make_decision()
    token = authorizer.issue(decision, make_binding()).model_copy(update=change)
    assert refusal(authorizer, decision, token) == INVALID_SIGNATURE


def test_token_signed_with_another_key_is_refused(ledger: InMemoryAuthorizationLedger, clock: Clock) -> None:
    decision = make_decision()
    token = CommitAuthorizer(b"other-key", ledger, clock=clock).issue(decision, make_binding())
    assert refusal(CommitAuthorizer(KEY, ledger, clock=clock), decision, token) == INVALID_SIGNATURE


def test_expired_token_is_refused_and_burned(authorizer: CommitAuthorizer, clock: Clock) -> None:
    decision = make_decision()
    token = authorizer.issue(decision, make_binding())
    clock.now = token.expiry + timedelta(seconds=1)
    assert refusal(authorizer, decision, token) == TOKEN_EXPIRED
    clock.now = T0
    assert refusal(authorizer, decision, token) == TOKEN_REUSED


def test_token_at_its_expiry_is_still_valid(authorizer: CommitAuthorizer, clock: Clock) -> None:
    decision = make_decision()
    token = authorizer.issue(decision, make_binding())
    clock.now = token.expiry
    authorizer.redeem(decision, token)


def test_altered_actions_are_refused_and_burn_the_token(authorizer: CommitAuthorizer) -> None:
    token = authorizer.issue(make_decision(quantity=6), make_binding())
    assert refusal(authorizer, make_decision(quantity=7), token) == ACTION_MISMATCH
    assert refusal(authorizer, make_decision(quantity=6), token) == TOKEN_REUSED


def test_reordered_actions_are_refused(authorizer: CommitAuthorizer) -> None:
    decision = make_decision()
    token = authorizer.issue(decision, make_binding())
    reordered = decision.model_copy(update={"proposed_actions": list(reversed(decision.proposed_actions))})
    assert refusal(authorizer, reordered, token) == ACTION_MISMATCH


def test_token_for_another_decision_is_refused(authorizer: CommitAuthorizer) -> None:
    token = authorizer.issue(make_decision("dec-1"), make_binding())
    assert refusal(authorizer, make_decision("dec-2"), token) == ACTION_MISMATCH


def test_binding_for_another_decision_cannot_be_issued(authorizer: CommitAuthorizer) -> None:
    with pytest.raises(AuthorizationError) as caught:
        authorizer.issue(make_decision("dec-1"), make_binding("dec-2"))
    assert caught.value.code == ACTION_MISMATCH


def test_token_the_ledger_never_issued_is_refused(clock: Clock) -> None:
    decision = make_decision()
    token = CommitAuthorizer(KEY, InMemoryAuthorizationLedger(), clock=clock).issue(decision, make_binding())
    # Same key, but a ledger that did not issue this nonce (another process).
    assert refusal(CommitAuthorizer(KEY, InMemoryAuthorizationLedger(), clock=clock), decision, token) == UNKNOWN_TOKEN


def test_without_a_key_nothing_is_issued_or_redeemed(ledger: InMemoryAuthorizationLedger, clock: Clock) -> None:
    keyless = CommitAuthorizer(None, ledger, clock=clock)
    assert keyless.can_issue is False
    with pytest.raises(SigningKeyMissing):
        keyless.issue(make_decision(), make_binding())
    token = CommitAuthorizer(KEY, ledger, clock=clock).issue(make_decision(), make_binding())
    assert refusal(keyless, make_decision(), token) == INVALID_SIGNATURE


def test_from_env_reads_key_and_ttl(ledger: InMemoryAuthorizationLedger, clock: Clock) -> None:
    authorizer = CommitAuthorizer.from_env(ledger, {SIGNING_KEY_ENV: " k ", TOKEN_TTL_ENV: "5"}, clock=clock)
    assert authorizer.can_issue
    assert authorizer.issue(make_decision(), make_binding()).expiry == T0 + timedelta(seconds=5)


def test_from_env_without_key_cannot_issue(ledger: InMemoryAuthorizationLedger) -> None:
    assert CommitAuthorizer.from_env(ledger, {}).can_issue is False


def test_from_env_reads_process_environment(ledger: InMemoryAuthorizationLedger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SIGNING_KEY_ENV, "process-key")
    assert CommitAuthorizer.from_env(ledger).can_issue


@pytest.mark.parametrize("raw", ["0", "-3", "soon"])
def test_from_env_rejects_bad_ttl(ledger: InMemoryAuthorizationLedger, raw: str) -> None:
    with pytest.raises(ValueError):
        CommitAuthorizer.from_env(ledger, {SIGNING_KEY_ENV: "k", TOKEN_TTL_ENV: raw})


def test_default_clock_issues_utc_tokens(ledger: InMemoryAuthorizationLedger) -> None:
    token = CommitAuthorizer(KEY, ledger).issue(make_decision(), make_binding(expiry=datetime.now(timezone.utc) + timedelta(minutes=1)))
    assert token.issued_at.tzinfo is not None


def test_ledger_revoke_closes_an_open_nonce(ledger: InMemoryAuthorizationLedger) -> None:
    ledger.issue("n1", T0)
    ledger.revoke("n1")
    assert ledger.consume("n1") == TOKEN_REUSED
    assert ledger.consume("never") == UNKNOWN_TOKEN
