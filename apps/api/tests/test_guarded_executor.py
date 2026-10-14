"""Guarded Executor and commit service (#18): only a valid authorization changes the Live Twin."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from retailtwin_api.agents.executor import (
    COMMITTED,
    EXECUTION_FAILED,
    CommitService,
    GuardedExecutor,
    build_commit_service,
)
from retailtwin_api.contracts import (
    ActionUnion,
    ChangeFacings,
    DCGVerdict,
    Decision,
    EvidenceBundle,
    ExpectedImpact,
    MoveProduct,
    ReplenishShelf,
)
from retailtwin_api.firestore_twin import (
    InMemoryTwinRepository,
    InventoryDocument,
    InventorySeed,
    StoreDocument,
)
from retailtwin_api.guard.decision_context_guard import (
    INSUFFICIENT_EVIDENCE,
    POLICY_THRESHOLD,
    VERSION_STALE,
    DecisionContextGuard,
    GuardPolicy,
    InMemoryGuardAudit,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.authorization import (
    ACTION_MISMATCH,
    MISSING_TOKEN,
    SIGNING_KEY_ENV,
    TOKEN_EXPIRED,
    TOKEN_REUSED,
    CommitAuthorizer,
    InMemoryAuthorizationLedger,
    SignedAuthorization,
)

STORE = "store-001"
T0 = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class FlakyTwin(InMemoryTwinRepository):
    """In-memory twin that can fail or race on chosen calls."""

    def __init__(self) -> None:
        super().__init__()
        self.race_commit = False
        self.fail_commit = False
        self.fail_get = False
        self.stale_get: dict[str, int] = {}
        self.commits: list[list[tuple[str, int]]] = []

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        if self.fail_get:
            raise RuntimeError("backend detail")
        doc = super().get_inventory(store_id, sku)
        if doc is not None and sku in self.stale_get:
            return doc.model_copy(update={"version": self.stale_get[sku]})
        return doc

    def commit_inventory(self, store_id: str, items: Sequence[tuple[InventoryDocument, int]]) -> StoreDocument:
        if self.fail_commit:
            raise RuntimeError("backend detail")
        if self.race_commit:
            # Another writer lands on the first SKU just before this commit.
            first = super().get_inventory(store_id, items[0][0].sku)
            assert first is not None
            super().upsert_inventory(first.model_copy(update={"version": first.version + 1}), first.version)
        store = super().commit_inventory(store_id, items)
        self.commits.append([(item.sku, item.version) for item, _ in items])
        return store


@pytest.fixture
def twin() -> FlakyTwin:
    repo = FlakyTwin()
    repo.seed(
        STORE,
        "v7",
        [
            InventorySeed(sku="P001", shelf_id="SH1", slot_id="S1", facings=2, shelf_quantity=10, backroom_quantity=30),
            InventorySeed(sku="P002", shelf_id="SH1", slot_id="S2", facings=3, shelf_quantity=4, backroom_quantity=9),
        ],
    )
    return repo


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def audit() -> InMemoryGuardAudit:
    return InMemoryGuardAudit()


@pytest.fixture
def parts(twin: FlakyTwin, clock: Clock, audit: InMemoryGuardAudit) -> tuple[NoStaleCommit, CommitAuthorizer, GuardedExecutor]:
    gate = NoStaleCommit(DecisionContextGuard(twin, clock=clock), audit, clock=clock)
    authorizer = CommitAuthorizer(b"k", InMemoryAuthorizationLedger(), clock=clock)
    return gate, authorizer, GuardedExecutor(twin, authorizer, gate, clock=clock)


def decision(actions: Sequence[ActionUnion] | None = None, versions: dict[str, str] | None = None, **extra: Any) -> Decision:
    fields: dict[str, Any] = {
        "decision_id": "dec-1",
        "agent_id": "planner",
        "context_version": f"{STORE}:v7",
        "context_timestamp": T0,
        "evidence": [
            EvidenceBundle(
                bundle_id="b1", provenance="tool-registry", source="investigator",
                entity_versions=versions or {"P001": "1"}, collected_at=T0, freshness=T0,
                store_id=STORE, correlation_id="corr-1", is_sufficient=True,
            )
        ],
        "proposed_actions": list(actions) if actions is not None else [ReplenishShelf(sku="P001", quantity=6)],
        "expected_impact": ExpectedImpact(kpi_score=0.2, description="restock"),
    }
    fields.update(extra)
    return Decision(**fields)


def authorize(parts: tuple[NoStaleCommit, CommitAuthorizer, GuardedExecutor], d: Decision) -> SignedAuthorization:
    gate, authorizer, _ = parts
    result, binding = gate.authorize(d)
    assert result.verdict is DCGVerdict.ALLOW, result
    assert binding is not None
    return authorizer.issue(d, binding)


def live(twin: InMemoryTwinRepository) -> list[dict[str, Any]]:
    return [doc.model_dump(exclude={"updated_at"}) for doc in sorted(twin.list_inventory(STORE), key=lambda d: d.sku)]


def bump(twin: InMemoryTwinRepository, sku: str) -> None:
    doc = twin.get_inventory(STORE, sku)
    assert doc is not None
    InMemoryTwinRepository.upsert_inventory(twin, doc.model_copy(update={"version": doc.version + 1}), doc.version)


# ─── Valid commit ────────────────────────────────────────────────────────────


def test_valid_token_commits_exactly_the_actions(parts, twin: FlakyTwin) -> None:
    d = decision([ReplenishShelf(sku="P001", quantity=6), ChangeFacings(sku="P001", facings=4)])
    outcome = parts[2].commit(d, authorize(parts, d))

    assert (outcome.status, outcome.reason_code) == ("committed", COMMITTED)
    assert outcome.committed
    assert [r.status for r in outcome.results] == ["applied", "applied"]
    assert [r.action_id for r in outcome.results] == ["dec-1:0", "dec-1:1"]
    p001 = twin.get_inventory(STORE, "P001")
    assert p001 is not None
    assert (p001.shelf_quantity, p001.backroom_quantity, p001.facings, p001.version) == (16, 24, 4, 2)
    # Two actions on one SKU are one write and one version step, in one commit.
    assert twin.commits == [[("P001", 2)]]
    assert outcome.entity_versions == {"P001": 2}
    assert outcome.store_version == "v8"
    store = twin.get_store(STORE)
    assert store is not None and store.version == "v8"
    assert outcome.guard is not None and outcome.guard.verdict is DCGVerdict.ALLOW


def test_move_changes_only_the_slot(parts, twin: FlakyTwin) -> None:
    d = decision([MoveProduct(sku="P001", from_slot="S1", to_slot="S9")])
    assert parts[2].commit(d, authorize(parts, d)).committed
    p001 = twin.get_inventory(STORE, "P001")
    assert p001 is not None and (p001.slot_id, p001.shelf_id) == ("S9", "SH1")


def test_untouched_skus_keep_their_version(parts, twin: FlakyTwin) -> None:
    d = decision()
    parts[2].commit(d, authorize(parts, d))
    p002 = twin.get_inventory(STORE, "P002")
    assert p002 is not None and p002.version == 1


# ─── Refused tokens leave Live unchanged ─────────────────────────────────────


def test_missing_token_changes_nothing(parts, twin: FlakyTwin) -> None:
    before = live(twin)
    outcome = parts[2].commit(decision(), None)
    assert (outcome.status, outcome.reason_code) == ("refused", MISSING_TOKEN)
    assert [r.status for r in outcome.results] == ["not_applied"]
    assert outcome.results[0].error == MISSING_TOKEN
    assert live(twin) == before


def test_expired_token_changes_nothing(parts, twin: FlakyTwin, clock: Clock) -> None:
    d = decision()
    token = authorize(parts, d)
    before = live(twin)
    clock.now = token.expiry + timedelta(seconds=1)
    assert parts[2].commit(d, token).reason_code == TOKEN_EXPIRED
    assert live(twin) == before


def test_altered_action_changes_nothing(parts, twin: FlakyTwin) -> None:
    token = authorize(parts, decision([ReplenishShelf(sku="P001", quantity=6)]))
    before = live(twin)
    altered = decision([ReplenishShelf(sku="P001", quantity=30)])
    assert parts[2].commit(altered, token).reason_code == ACTION_MISMATCH
    assert live(twin) == before


def test_reused_token_changes_nothing_the_second_time(parts, twin: FlakyTwin) -> None:
    d = decision()
    token = authorize(parts, d)
    assert parts[2].commit(d, token).committed
    after_first = live(twin)
    assert parts[2].commit(d, token).reason_code == TOKEN_REUSED
    assert live(twin) == after_first


def test_tampered_token_changes_nothing(parts, twin: FlakyTwin) -> None:
    d = decision()
    token = authorize(parts, d).model_copy(update={"entity_versions": {"P001": 5}})
    before = live(twin)
    assert parts[2].commit(d, token).status == "refused"
    assert live(twin) == before


# ─── No-Stale-Commit at the write ────────────────────────────────────────────


def test_version_n_plus_one_after_authorization_blocks_the_commit(parts, twin: FlakyTwin, audit: InMemoryGuardAudit) -> None:
    d = decision()
    token = authorize(parts, d)
    bump(twin, "P001")
    before = live(twin)

    outcome = parts[2].commit(d, token)

    assert (outcome.status, outcome.reason_code) == ("refused", VERSION_STALE)
    assert outcome.guard is not None and outcome.guard.verdict is DCGVerdict.REFRESH_REQUIRED
    assert live(twin) == before
    assert [(e.stage, e.reason_code) for e in audit.events("dec-1")][-1] == ("commit", VERSION_STALE)


def test_version_moving_between_recheck_and_read_blocks_the_commit(parts, twin: FlakyTwin) -> None:
    d = decision()
    token = authorize(parts, d)
    gate, authorizer, _ = parts
    before = live(twin)

    class RacingGate:
        def recheck(self, decision: Decision, binding: Any):
            result = gate.recheck(decision, binding)
            twin.stale_get["P001"] = 2  # a write lands right after the recheck
            return result

    executor = GuardedExecutor(twin, authorizer, RacingGate())  # type: ignore[arg-type]
    assert executor.commit(d, token).reason_code == VERSION_STALE
    twin.stale_get.clear()
    assert live(twin) == before


def test_write_landing_before_the_commit_writes_nothing(parts, twin: FlakyTwin) -> None:
    d = decision(
        [ReplenishShelf(sku="P001", quantity=6), ReplenishShelf(sku="P002", quantity=1)],
        versions={"P001": "1", "P002": "1"},
    )
    token = authorize(parts, d)
    twin.race_commit = True

    outcome = parts[2].commit(d, token)

    assert (outcome.status, outcome.reason_code) == ("refused", VERSION_STALE)
    assert twin.commits == []
    p001 = twin.get_inventory(STORE, "P001")
    p002 = twin.get_inventory(STORE, "P002")
    assert p001 is not None and p002 is not None
    # Only the other writer's version step; neither SKU took this decision's change.
    assert (p001.shelf_quantity, p001.version, p002.shelf_quantity, p002.version) == (10, 2, 4, 1)
    store = twin.get_store(STORE)
    assert store is not None and store.version == "v7"


def test_failed_commit_writes_nothing(parts, twin: FlakyTwin) -> None:
    d = decision(
        [ReplenishShelf(sku="P001", quantity=6), ReplenishShelf(sku="P002", quantity=1)],
        versions={"P001": "1", "P002": "1"},
    )
    token = authorize(parts, d)
    twin.fail_commit = True
    before = live(twin)

    outcome = parts[2].commit(d, token)

    assert (outcome.status, outcome.reason_code) == ("failed", EXECUTION_FAILED)
    assert live(twin) == before


def test_failed_live_read_changes_nothing(parts, twin: FlakyTwin) -> None:
    d = decision()
    token = authorize(parts, d)
    gate, authorizer, _ = parts

    class ReadBreakingGate:
        def recheck(self, decision: Decision, binding: Any):
            result = gate.recheck(decision, binding)
            twin.fail_get = True
            return result

    outcome = GuardedExecutor(twin, authorizer, ReadBreakingGate()).commit(d, token)  # type: ignore[arg-type]
    twin.fail_get = False
    assert (outcome.status, outcome.reason_code) == ("failed", EXECUTION_FAILED)
    assert twin.commits == []


def test_sku_deleted_before_the_write_changes_nothing(parts, twin: FlakyTwin) -> None:
    d = decision()
    token = authorize(parts, d)
    gate, authorizer, _ = parts

    class DeletingGate:
        def recheck(self, decision: Decision, binding: Any):
            result = gate.recheck(decision, binding)
            twin.reset(STORE)
            return result

    outcome = GuardedExecutor(twin, authorizer, DeletingGate()).commit(d, token)  # type: ignore[arg-type]
    assert outcome.reason_code == EXECUTION_FAILED
    assert twin.commits == []


# ─── Commit service ──────────────────────────────────────────────────────────


@pytest.fixture
def service(parts) -> CommitService:
    gate, authorizer, executor = parts
    return CommitService(gate, authorizer, executor)


def test_service_commits_an_allowed_decision(service: CommitService, twin: FlakyTwin) -> None:
    outcome = service.approve(decision())
    assert (outcome.verdict, outcome.reason_code, outcome.committed) == (DCGVerdict.ALLOW, COMMITTED, True)
    assert service.can_commit


def test_service_issues_no_token_when_the_guard_refuses(service: CommitService, twin: FlakyTwin) -> None:
    bump(twin, "P001")
    outcome = service.approve(decision())
    assert (outcome.verdict, outcome.reason_code, outcome.commit) == (DCGVerdict.REFRESH_REQUIRED, VERSION_STALE, None)
    assert not outcome.committed


def test_service_reports_insufficient_evidence(service: CommitService) -> None:
    d = decision()
    d = d.model_copy(update={"evidence": [d.evidence[0].model_copy(update={"is_sufficient": False})]})
    outcome = service.approve(d)
    assert (outcome.verdict, outcome.reason_code) == (DCGVerdict.DENY, INSUFFICIENT_EVIDENCE)


def test_service_routes_large_changes_to_a_person(twin: FlakyTwin, clock: Clock, audit: InMemoryGuardAudit) -> None:
    gate = NoStaleCommit(DecisionContextGuard(twin, GuardPolicy(max_replenish_units=5), clock=clock), audit, clock=clock)
    authorizer = CommitAuthorizer(b"k", InMemoryAuthorizationLedger(), clock=clock)
    service = CommitService(gate, authorizer, GuardedExecutor(twin, authorizer, gate, clock=clock))
    outcome = service.approve(decision())
    assert (outcome.verdict, outcome.reason_code) == (DCGVerdict.HUMAN_REVIEW, POLICY_THRESHOLD)


def test_service_maps_a_write_race_to_refresh(service: CommitService, twin: FlakyTwin) -> None:
    twin.race_commit = True
    outcome = service.approve(decision())
    assert (outcome.verdict, outcome.reason_code) == (DCGVerdict.REFRESH_REQUIRED, VERSION_STALE)


def test_service_maps_an_execution_failure_to_deny(service: CommitService, twin: FlakyTwin) -> None:
    twin.fail_commit = True
    outcome = service.approve(decision())
    assert (outcome.verdict, outcome.reason_code) == (DCGVerdict.DENY, EXECUTION_FAILED)
    assert outcome.commit is not None and outcome.commit.status == "failed"


def test_service_maps_a_commit_time_guard_refusal(parts, twin: FlakyTwin) -> None:
    gate, authorizer, executor = parts

    class StaleAtCommit(GuardedExecutor):
        def commit(self, decision: Decision, token: SignedAuthorization | None):
            bump(twin, "P001")
            return executor.commit(decision, token)

    service = CommitService(gate, authorizer, StaleAtCommit(twin, authorizer, gate))
    outcome = service.approve(decision())
    assert (outcome.verdict, outcome.reason_code) == (DCGVerdict.REFRESH_REQUIRED, VERSION_STALE)


def test_build_commit_service_outside_production_uses_a_process_key(twin: FlakyTwin, audit: InMemoryGuardAudit) -> None:
    now = datetime.now(timezone.utc)
    service = build_commit_service(twin, audit, production=False, environ={})
    assert service.can_commit
    d = decision(context_timestamp=now)
    d = d.model_copy(update={"evidence": [d.evidence[0].model_copy(update={"freshness": now})]})
    assert service.approve(d).committed


def test_build_commit_service_in_production_needs_a_key(twin: FlakyTwin, audit: InMemoryGuardAudit) -> None:
    assert build_commit_service(twin, audit, production=True, environ={}).can_commit is False
    assert build_commit_service(twin, audit, production=True, environ={SIGNING_KEY_ENV: "k"}).can_commit


def test_build_commit_service_reads_process_environment(
    twin: FlakyTwin, audit: InMemoryGuardAudit, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SIGNING_KEY_ENV, "process-key")
    assert build_commit_service(twin, audit, production=True).can_commit
