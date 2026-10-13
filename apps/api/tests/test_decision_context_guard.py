"""Decision Context Guard gates (#16)."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import pytest

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
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventoryDocument, InventorySeed
from retailtwin_api.guard.decision_context_guard import (
    ACTION_NOT_ALLOWED,
    ALLOWED,
    CONFLICTING_EVIDENCE,
    CONTEXT_EXPIRED,
    GATES,
    INFEASIBLE_ACTION,
    INSUFFICIENT_EVIDENCE,
    INVALID_DECISION,
    MISSING_CONTEXT_VERSION,
    POLICY_THRESHOLD,
    TWIN_UNAVAILABLE,
    UNKNOWN_ENTITY,
    VERSION_STALE,
    DecisionContextGuard,
    GuardPolicy,
    PolicyConfigError,
    action_hash,
    canonical_action,
    context_hash,
)
from retailtwin_api.guard.decision_context_guard.hashing import action_type

STORE = "store-001"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def twin() -> InMemoryTwinRepository:
    repo = InMemoryTwinRepository()
    repo.seed(
        STORE,
        "v1",
        [
            InventorySeed(sku="P001", shelf_id="SH1", slot_id="S1", facings=2, shelf_quantity=10, backroom_quantity=30),
            InventorySeed(sku="P002", shelf_id="SH1", slot_id="S2", facings=3, shelf_quantity=4, backroom_quantity=0),
            InventorySeed(sku="P003", shelf_id="SH2", slot_id="S3", facings=1, shelf_quantity=6, backroom_quantity=8),
        ],
    )
    return repo


@pytest.fixture
def guard(twin: InMemoryTwinRepository) -> DecisionContextGuard:
    return DecisionContextGuard(twin, clock=lambda: NOW)


def bundle(
    versions: dict[str, str] | None = None,
    *,
    sufficient: bool = True,
    freshness: datetime = NOW - timedelta(seconds=10),
    store_id: str = STORE,
    bundle_id: str = "bundle-1",
    correlation_id: str = "corr-1",
    collected_at: datetime | None = None,
) -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id=bundle_id,
        provenance="tool-registry",
        source="investigator",
        entity_versions={"P001": "1"} if versions is None else versions,
        collected_at=freshness if collected_at is None else collected_at,
        freshness=freshness,
        store_id=store_id,
        correlation_id=correlation_id,
        is_sufficient=sufficient,
    )


def decision(
    actions: Sequence[ActionUnion] | None = None,
    *,
    evidence: list[EvidenceBundle] | None = None,
    context_timestamp: datetime = NOW - timedelta(seconds=5),
    **overrides: Any,
) -> Decision:
    fields: dict[str, Any] = {
        "decision_id": "dec-1",
        "agent_id": "planner",
        "context_version": f"{STORE}:v1",
        "context_timestamp": context_timestamp,
        "evidence": [bundle()] if evidence is None else evidence,
        "proposed_actions": list(actions) if actions is not None else [ReplenishShelf(sku="P001", quantity=12)],
        "simulation_id": "sim-1",
        "expected_impact": ExpectedImpact(kpi_score=0.4, description="fewer stockouts"),
    }
    fields.update(overrides)
    return Decision(**fields)


def bump(twin: InMemoryTwinRepository, sku: str) -> None:
    doc = twin.get_inventory(STORE, sku)
    assert doc is not None
    twin.upsert_inventory(doc.model_copy(update={"version": doc.version + 1}), expected_version=doc.version)


# ─── ALLOW ────────────────────────────────────────────────────────────────────


def test_valid_decision_is_allowed(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision())

    assert result.verdict is DCGVerdict.ALLOW
    assert result.reason_code == ALLOWED
    assert result.context_version == f"{STORE}:v1"
    assert result.policy_result["failed_gate"] is None
    assert [check["gate"] for check in result.policy_result["checks"]] == list(GATES)
    assert all(check["passed"] for check in result.policy_result["checks"])
    assert result.policy_result["entity_versions"] == {"P001": "1"}
    # The decision stays valid until its oldest context ages out.
    assert result.expiry == NOW - timedelta(seconds=10) + timedelta(seconds=120)


def test_allow_hash_binds_decision_versions_and_actions(guard: DecisionContextGuard) -> None:
    actions = [ReplenishShelf(sku="P001", quantity=12)]
    result = guard.evaluate(decision(actions))

    assert result.context_hash == context_hash("dec-1", STORE, {"P001": "1"}, actions)
    assert result.context_hash != context_hash("dec-1", STORE, {"P001": "2"}, actions)
    assert result.context_hash != context_hash("dec-1", STORE, {"P001": "1"}, [ReplenishShelf(sku="P001", quantity=13)])


def test_same_decision_and_state_give_the_same_result(guard: DecisionContextGuard) -> None:
    assert guard.evaluate(decision()) == guard.evaluate(decision())


def test_guard_does_not_change_the_live_twin(guard: DecisionContextGuard, twin: InMemoryTwinRepository) -> None:
    before = [doc.model_dump() for doc in twin.list_inventory(STORE)]
    guard.evaluate(
        decision(
            [ReplenishShelf(sku="P001", quantity=5), MoveProduct(sku="P001", from_slot="S1", to_slot="S9")]
        )
    )
    assert [doc.model_dump() for doc in twin.list_inventory(STORE)] == before


# ─── Gate 1: integrity ───────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["decision_id", "agent_id", "context_version"])
def test_blank_identity_field_is_denied(guard: DecisionContextGuard, field: str) -> None:
    result = guard.evaluate(decision(**{field: "  "}))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)
    assert result.policy_result["failed_gate"] == "integrity"


def test_decision_without_actions_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_decision_without_evidence_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_evidence_from_two_stores_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(), bundle(store_id="store-002", bundle_id="b2")]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_evidence_from_two_investigations_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(
        decision(evidence=[bundle(), bundle({"P001": "1"}, bundle_id="b2", correlation_id="corr-2")])
    )
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)
    assert "correlation" in result.policy_result["checks"][0]["detail"]


def test_blank_correlation_id_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(correlation_id="  ")]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_result_and_logs_carry_the_correlation_id(
    guard: DecisionContextGuard, twin: InMemoryTwinRepository, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="retailtwin_api.guard.decision_context_guard.guard")
    assert guard.evaluate(decision()).policy_result["correlation_id"] == "corr-1"
    bump(twin, "P001")
    assert guard.evaluate(decision()).policy_result["correlation_id"] == "corr-1"
    assert all("correlation_id=corr-1" in record.getMessage() for record in caplog.records)
    assert len(caplog.records) == 2


def test_read_failure_log_carries_the_correlation_id(
    twin: InMemoryTwinRepository, caplog: pytest.LogCaptureFixture
) -> None:
    guard = DecisionContextGuard(_BrokenTwin(twin, fail_get=True), clock=lambda: NOW)
    guard.evaluate(decision())
    assert any(
        "live read failed" in r.getMessage() and "correlation_id=corr-1" in r.getMessage() for r in caplog.records
    )


def test_duplicate_action_for_one_sku_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(
        decision([ReplenishShelf(sku="P001", quantity=1), ReplenishShelf(sku="P001", quantity=2)])
    )
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_naive_timestamp_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(context_timestamp=datetime(2026, 10, 13, 8, 59)))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_future_timestamp_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(freshness=NOW + timedelta(minutes=1))]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_naive_collected_at_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(collected_at=datetime(2026, 10, 13, 8, 59))]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_future_collected_at_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(collected_at=NOW + timedelta(minutes=1))]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INVALID_DECISION)


def test_collected_at_does_not_extend_the_expiry(guard: DecisionContextGuard) -> None:
    """An old collection time is valid; expiry still follows context_timestamp and freshness."""
    result = guard.evaluate(
        decision(evidence=[bundle(freshness=NOW - timedelta(seconds=10), collected_at=NOW - timedelta(seconds=50))])
    )
    assert result.verdict is DCGVerdict.ALLOW
    assert result.expiry == NOW - timedelta(seconds=10) + timedelta(seconds=120)


def test_timestamp_within_clock_skew_is_accepted(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(context_timestamp=NOW + timedelta(seconds=3)))
    assert result.verdict is DCGVerdict.ALLOW


# ─── Gate 2: evidence ────────────────────────────────────────────────────────


def test_insufficient_evidence_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(sufficient=False)]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INSUFFICIENT_EVIDENCE)
    assert result.policy_result["failed_gate"] == "evidence"


def test_bundles_that_disagree_on_a_version_are_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle({"P001": "1"}), bundle({"P001": "2"}, bundle_id="b2")]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, CONFLICTING_EVIDENCE)


def test_versions_merge_across_bundles(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(
        decision(
            [ReplenishShelf(sku="P001", quantity=1), ReplenishShelf(sku="P003", quantity=1)],
            evidence=[bundle({"P001": "1"}), bundle({"P003": "1"}, bundle_id="b2")],
        )
    )
    assert result.verdict is DCGVerdict.ALLOW
    assert result.policy_result["entity_versions"] == {"P001": "1", "P003": "1"}


# ─── Gate 3: context version ─────────────────────────────────────────────────


def test_action_on_sku_without_evidence_version_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([ReplenishShelf(sku="P003", quantity=1)]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, MISSING_CONTEXT_VERSION)
    assert result.policy_result["failed_gate"] == "context"


def test_action_on_unknown_sku_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([ReplenishShelf(sku="P404", quantity=1)], evidence=[bundle({"P404": "1"})]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, UNKNOWN_ENTITY)


def test_changed_sku_requires_refresh(guard: DecisionContextGuard, twin: InMemoryTwinRepository) -> None:
    bump(twin, "P001")
    result = guard.evaluate(decision())
    assert (result.verdict, result.reason_code) == (DCGVerdict.REFRESH_REQUIRED, VERSION_STALE)
    assert result.policy_result["entity_versions"] == {"P001": "2"}
    assert result.expiry == NOW


def test_change_to_an_untouched_sku_does_not_block(guard: DecisionContextGuard, twin: InMemoryTwinRepository) -> None:
    bump(twin, "P003")
    assert guard.evaluate(decision()).verdict is DCGVerdict.ALLOW


class _BrokenTwin:
    def __init__(self, inner: InMemoryTwinRepository, *, fail_get: bool = False, fail_list: bool = False) -> None:
        self._inner = inner
        self._fail_get = fail_get
        self._fail_list = fail_list

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        if self._fail_get:
            raise RuntimeError("secret backend detail")
        return self._inner.get_inventory(store_id, sku)

    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]:
        if self._fail_list:
            raise RuntimeError("secret backend detail")
        return self._inner.list_inventory(store_id)


def test_live_read_failure_fails_closed(twin: InMemoryTwinRepository) -> None:
    guard = DecisionContextGuard(_BrokenTwin(twin, fail_get=True), clock=lambda: NOW)
    result = guard.evaluate(decision())
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, TWIN_UNAVAILABLE)
    assert "secret" not in str(result.policy_result)


def test_live_list_failure_fails_closed(twin: InMemoryTwinRepository) -> None:
    guard = DecisionContextGuard(_BrokenTwin(twin, fail_list=True), clock=lambda: NOW)
    result = guard.evaluate(decision([MoveProduct(sku="P001", from_slot="S1", to_slot="S9")]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, TWIN_UNAVAILABLE)


# ─── Gate 4: freshness ───────────────────────────────────────────────────────


def test_old_evidence_requires_refresh(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(freshness=NOW - timedelta(seconds=121))]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.REFRESH_REQUIRED, CONTEXT_EXPIRED)
    assert result.policy_result["failed_gate"] == "freshness"


def test_old_decision_requires_refresh(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(context_timestamp=NOW - timedelta(minutes=5)))
    assert (result.verdict, result.reason_code) == (DCGVerdict.REFRESH_REQUIRED, CONTEXT_EXPIRED)


def test_context_exactly_at_the_limit_is_fresh(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision(evidence=[bundle(freshness=NOW - timedelta(seconds=120))]))
    assert result.verdict is DCGVerdict.ALLOW


def test_version_gate_runs_before_freshness(guard: DecisionContextGuard, twin: InMemoryTwinRepository) -> None:
    bump(twin, "P001")
    result = guard.evaluate(decision(evidence=[bundle(freshness=NOW - timedelta(hours=1))]))
    assert result.reason_code == VERSION_STALE


# ─── Gate 5: physical feasibility ────────────────────────────────────────────


def test_replenish_beyond_backroom_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([ReplenishShelf(sku="P001", quantity=31)]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INFEASIBLE_ACTION)
    assert result.policy_result["failed_gate"] == "feasibility"


def test_replenish_of_whole_backroom_is_allowed(guard: DecisionContextGuard) -> None:
    assert guard.evaluate(decision([ReplenishShelf(sku="P001", quantity=30)])).verdict is DCGVerdict.ALLOW


def test_facings_above_slot_limit_are_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([ChangeFacings(sku="P001", facings=13)]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INFEASIBLE_ACTION)


def test_facings_at_slot_limit_are_allowed(guard: DecisionContextGuard) -> None:
    assert guard.evaluate(decision([ChangeFacings(sku="P001", facings=12)])).verdict is DCGVerdict.ALLOW


def test_move_from_wrong_slot_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([MoveProduct(sku="P001", from_slot="S2", to_slot="S9")]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INFEASIBLE_ACTION)


def test_move_to_same_slot_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([MoveProduct(sku="P001", from_slot="S1", to_slot="S1")]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INFEASIBLE_ACTION)


def test_move_into_occupied_slot_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([MoveProduct(sku="P001", from_slot="S1", to_slot="S2")]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INFEASIBLE_ACTION)
    assert "P002" in result.policy_result["checks"][-1]["detail"]


def test_move_into_empty_slot_is_allowed(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(decision([MoveProduct(sku="P001", from_slot="S1", to_slot="S9")]))
    assert result.verdict is DCGVerdict.ALLOW


def test_swap_through_a_freed_slot_is_allowed(guard: DecisionContextGuard) -> None:
    """P003 may take S1 once P001 has left it within the same decision."""
    result = guard.evaluate(
        decision(
            [
                MoveProduct(sku="P001", from_slot="S1", to_slot="S9"),
                MoveProduct(sku="P003", from_slot="S3", to_slot="S1"),
            ],
            evidence=[bundle({"P001": "1", "P003": "1"})],
        )
    )
    assert result.verdict is DCGVerdict.ALLOW


def test_actions_are_checked_against_the_state_earlier_actions_leave(guard: DecisionContextGuard) -> None:
    """After moving P001 to S9, a second action that still assumes S1 does not fit."""
    result = guard.evaluate(
        decision(
            [
                MoveProduct(sku="P001", from_slot="S1", to_slot="S9"),
                MoveProduct(sku="P003", from_slot="S3", to_slot="S9"),
            ],
            evidence=[bundle({"P001": "1", "P003": "1"})],
        )
    )
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INFEASIBLE_ACTION)


def test_replenish_from_an_empty_backroom_is_denied(guard: DecisionContextGuard) -> None:
    result = guard.evaluate(
        decision(
            [ChangeFacings(sku="P002", facings=4), ReplenishShelf(sku="P002", quantity=1)],
            evidence=[bundle({"P002": "1"})],
        )
    )
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, INFEASIBLE_ACTION)


# ─── Gate 6: policy ──────────────────────────────────────────────────────────


def test_action_type_outside_allow_list_is_denied(twin: InMemoryTwinRepository) -> None:
    policy = GuardPolicy(allowed_actions=frozenset({"replenish_shelf"}))
    guard = DecisionContextGuard(twin, policy, clock=lambda: NOW)
    result = guard.evaluate(decision([ChangeFacings(sku="P001", facings=3)]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.DENY, ACTION_NOT_ALLOWED)
    assert result.policy_result["failed_gate"] == "policy"


def test_too_many_actions_need_human_review(twin: InMemoryTwinRepository) -> None:
    guard = DecisionContextGuard(twin, GuardPolicy(max_actions=1), clock=lambda: NOW)
    result = guard.evaluate(
        decision([ReplenishShelf(sku="P001", quantity=1), ChangeFacings(sku="P001", facings=3)])
    )
    assert (result.verdict, result.reason_code) == (DCGVerdict.HUMAN_REVIEW, POLICY_THRESHOLD)


def test_large_replenishment_needs_human_review(twin: InMemoryTwinRepository) -> None:
    guard = DecisionContextGuard(twin, GuardPolicy(max_replenish_units=10), clock=lambda: NOW)
    result = guard.evaluate(decision([ReplenishShelf(sku="P001", quantity=11)]))
    assert (result.verdict, result.reason_code) == (DCGVerdict.HUMAN_REVIEW, POLICY_THRESHOLD)
    assert result.expiry == NOW


def test_feasibility_runs_before_policy(twin: InMemoryTwinRepository) -> None:
    guard = DecisionContextGuard(twin, GuardPolicy(max_replenish_units=10), clock=lambda: NOW)
    assert guard.evaluate(decision([ReplenishShelf(sku="P001", quantity=40)])).reason_code == INFEASIBLE_ACTION


# ─── Policy configuration ────────────────────────────────────────────────────


def test_policy_defaults() -> None:
    policy = GuardPolicy.from_env({})
    assert policy == GuardPolicy()
    assert policy.freshness == timedelta(seconds=120)


def test_policy_reads_environment() -> None:
    policy = GuardPolicy.from_env(
        {
            "RETAILTWIN_DCG_FRESHNESS_SECONDS": "300",
            "RETAILTWIN_DCG_MAX_FACINGS": "6",
            "RETAILTWIN_DCG_MAX_ACTIONS": "2",
            "RETAILTWIN_DCG_MAX_REPLENISH_UNITS": " ",
        }
    )
    assert policy.freshness == timedelta(seconds=300)
    assert (policy.max_facings, policy.max_actions, policy.max_replenish_units) == (6, 2, 200)


def test_policy_reads_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETAILTWIN_DCG_MAX_ACTIONS", "3")
    assert GuardPolicy.from_env().max_actions == 3


@pytest.mark.parametrize("raw", ["0", "-1", "abc"])
def test_policy_rejects_bad_values(raw: str) -> None:
    with pytest.raises(PolicyConfigError):
        GuardPolicy.from_env({"RETAILTWIN_DCG_MAX_FACINGS": raw})


def test_guard_exposes_policy(twin: InMemoryTwinRepository) -> None:
    policy = GuardPolicy(max_actions=2)
    assert DecisionContextGuard(twin, policy).policy is policy


def test_default_clock_is_utc(twin: InMemoryTwinRepository) -> None:
    guard = DecisionContextGuard(twin)
    now = datetime.now(timezone.utc)
    result = guard.evaluate(decision(context_timestamp=now, evidence=[bundle(freshness=now)]))
    assert result.verdict is DCGVerdict.ALLOW


# ─── Hashing ─────────────────────────────────────────────────────────────────


def test_canonical_action_names_the_type() -> None:
    assert canonical_action(MoveProduct(sku="P1", from_slot="A", to_slot="B")) == {
        "type": "move_product", "sku": "P1", "from_slot": "A", "to_slot": "B",
    }
    assert canonical_action(ChangeFacings(sku="P1", facings=2))["type"] == "change_facings"
    assert canonical_action(ReplenishShelf(sku="P1", quantity=2))["type"] == "replenish_shelf"


def test_action_hash_distinguishes_types_with_the_same_numbers() -> None:
    assert action_hash(ChangeFacings(sku="P1", facings=2)) != action_hash(ReplenishShelf(sku="P1", quantity=2))
    assert action_hash(ChangeFacings(sku="P1", facings=2)) == action_hash(ChangeFacings(sku="P1", facings=2))


def test_context_hash_ignores_version_order() -> None:
    actions = [ReplenishShelf(sku="P1", quantity=1)]
    assert context_hash("d", "s", {"a": "1", "b": "2"}, actions) == context_hash("d", "s", {"b": "2", "a": "1"}, actions)


def test_unknown_action_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        action_type(object())  # type: ignore[arg-type]


# ─── Provider neutrality ─────────────────────────────────────────────────────

GUARD_ROOT = Path(__file__).resolve().parents[1] / "retailtwin_api" / "guard"
FORBIDDEN = ("openai", "vertexai", "google.genai", "google.cloud", "retailtwin_api.llm", "retailtwin_api.demo_runtime")


@pytest.mark.parametrize("path", sorted(GUARD_ROOT.rglob("*.py")), ids=lambda p: p.name)
def test_guard_imports_no_model_sdk(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if name.startswith(FORBIDDEN)]
