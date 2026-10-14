"""Re-plan after a stale rejection: one new decision, or a bounded stop."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from retailtwin_api.agents.investigator.evidence import bind_read_port
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.replan import (
    COMMIT_FAILED,
    CONTEXT_MISMATCH,
    CONTEXT_UNAVAILABLE,
    EMPTY_PLAN,
    LINEAGE_MISMATCH,
    MAX_REFRESHES_ENV,
    PROVIDER_FAILED,
    SIMULATION_FAILED,
    UNSCORED_IMPACT,
    CommitPort,
    ContextVersionSource,
    ReplanConfigError,
    ReplanResult,
    ReplanStatus,
    SimulationPort,
    max_refreshes_from_env,
    replan,
)
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry, build_store_registry
from retailtwin_api.agents.planner.plans import INVALID_OUTPUT, UNSCORED_IMPACT
from retailtwin_api.contracts import (
    ChangeFacings,
    Decision,
    EvidenceBundle,
    ExpectedImpact,
    ReplenishShelf,
)
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventoryDocument, InventorySeed
from retailtwin_api.guard.decision_context_guard import (
    ALLOWED,
    INFEASIBLE_ACTION,
    POLICY_THRESHOLD,
    VERSION_STALE,
    DecisionContextGuard,
    InMemoryGuardAudit,
    NoStaleCommit,
)
from retailtwin_api.guard.decision_context_guard.no_stale_commit import CommitBinding
from retailtwin_api.llm.contracts import LlmProvider, LlmRequest, LlmResponse, LlmToolCall
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.schemas import ProductInventory, StoreEvent, StoreResponse

CORRELATION = "run-weekend-demand-surge-1"
STORE = "store-001"
SKU = "P017"
CONTEXT = "store-001:v1"
NEXT = "store-001:v2"
LATER = "store-001:v3"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
STALE_ID = f"plan-{CORRELATION}-{SKU}-stale"


class Boom(LlmProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.calls += 1
        raise RuntimeError("secret")


class Spy:
    def __init__(self) -> None:
        self.decisions: list[Decision] = []
        self.bindings: list[CommitBinding] = []

    def commit(self, decision: Decision, binding: CommitBinding) -> None:
        self.decisions.append(decision)
        self.bindings.append(binding)


class RaisingCommit:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def commit(self, decision: Decision, binding: CommitBinding) -> None:
        self.ids.append(decision.decision_id)
        raise RuntimeError("secret")


class TwinStore:
    def __init__(self, twin: Any) -> None:
        self._twin = twin

    def inventory(self, sku: str) -> ProductInventory | None:
        doc = self._twin.get_inventory(STORE, sku)
        if doc is None:
            return None
        return ProductInventory.model_validate(doc.to_product_inventory())

    def view(self) -> StoreResponse:
        products = [
            ProductInventory.model_validate(doc.to_product_inventory())
            for doc in self._twin.list_inventory(STORE)
        ]
        return StoreResponse(store_id=STORE, context_version=CONTEXT, version="v1", products=products)


class AdvancingTwin:
    """Every live read is one version ahead of the previous read."""

    def __init__(self, inner: InMemoryTwinRepository) -> None:
        self._inner = inner
        self.reads = 0

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        doc = self._inner.get_inventory(store_id, sku)
        if doc is None:
            return None
        self.reads += 1
        return doc.model_copy(update={"version": doc.version + self.reads})

    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]:
        return self._inner.list_inventory(store_id)


class StepTwin:
    """The first ``hold`` reads stay at the stored version. Later reads are one ahead."""

    def __init__(self, inner: InMemoryTwinRepository, *, hold: int = 2) -> None:
        self._inner = inner
        self._hold = hold
        self.reads = 0

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        doc = self._inner.get_inventory(store_id, sku)
        if doc is None:
            return None
        self.reads += 1
        if self.reads <= self._hold:
            return doc
        return doc.model_copy(update={"version": doc.version + 1})

    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]:
        return self._inner.list_inventory(store_id)


class ShiftAfter:
    """The first read matches the stored version. Later reads are one ahead."""

    def __init__(self, inner: InMemoryTwinRepository) -> None:
        self._inner = inner
        self.reads = 0

    def get_inventory(self, store_id: str, sku: str) -> InventoryDocument | None:
        doc = self._inner.get_inventory(store_id, sku)
        if doc is None:
            return None
        self.reads += 1
        if self.reads == 1:
            return doc
        return doc.model_copy(update={"version": doc.version + 1})

    def list_inventory(self, store_id: str) -> Sequence[InventoryDocument]:
        return self._inner.list_inventory(store_id)


def _repo(
    *,
    live_version: int = 2,
    backroom: int = 54,
    occupant: bool = False,
) -> InMemoryTwinRepository:
    repo = InMemoryTwinRepository()
    items = [
        InventorySeed(
            sku=SKU,
            shelf_id="A02",
            slot_id="A02-S03",
            facings=2,
            shelf_quantity=8,
            backroom_quantity=backroom,
        )
    ]
    if occupant:
        items.append(
            InventorySeed(
                sku="P099",
                shelf_id="B02",
                slot_id="B02-S01",
                facings=1,
                shelf_quantity=4,
                backroom_quantity=4,
            )
        )
    repo.seed(STORE, "v1", items)
    if live_version != 1:
        doc = repo.get_inventory(STORE, SKU)
        assert doc is not None
        repo.upsert_inventory(doc.model_copy(update={"version": live_version}), expected_version=1)
    return repo


def _registry(twin: Any) -> ToolRegistry:
    registry = build_store_registry(TwinStore(twin))

    def sales(args: Any) -> dict[str, Any]:
        return {"version": "evt-p017", "sku": args.sku, "observed_at": NOW.isoformat(), "sales": []}

    def forecast(args: Any) -> dict[str, Any]:
        return {
            "version": "forecast-demand-v1",
            "sku": args.sku,
            "forecast_units": "73",
            "formula_id": "forecast-demand-v1",
            "observed_at": NOW.isoformat(),
        }

    def promotions(args: Any) -> dict[str, Any]:
        return {"version": "0", "sku": args.sku, "observed_at": NOW.isoformat(), "promotions": []}

    def planogram(_args: Any) -> dict[str, Any]:
        return {
            "version": "1",
            "observed_at": NOW.isoformat(),
            "placements": [{"sku": SKU, "shelf_id": "A02", "slot_id": "A02-S03", "facings": 2}],
        }

    bind_read_port(registry, "get_sales_history", sales)
    bind_read_port(registry, "forecast_demand", forecast)
    bind_read_port(registry, "get_promotions", promotions)
    bind_read_port(registry, "get_planogram", planogram)
    return registry


def _calls() -> list[LlmToolCall]:
    return [
        LlmToolCall(id="inv", name="get_inventory", arguments={"sku": SKU}),
        LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": "A02"}),
        LlmToolCall(id="sales", name="get_sales_history", arguments={"sku": SKU, "window_hours": 4}),
        LlmToolCall(id="forecast", name="forecast_demand", arguments={"sku": SKU, "horizon_hours": 4}),
        LlmToolCall(id="promo", name="get_promotions", arguments={"sku": SKU}),
        LlmToolCall(id="plan", name="get_planogram", arguments={}),
    ]


def _canonical() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "reason": "Replenish P017 from the backroom.",
                "actions": [{"type": "replenish_shelf", "sku": SKU, "quantity": 12}],
            },
            {
                "reason": "Increase facings, then replenish P017.",
                "actions": [
                    {"type": "change_facings", "sku": SKU, "facings": 4},
                    {"type": "replenish_shelf", "sku": SKU, "quantity": 12},
                ],
            },
            {
                "reason": "Move P017, increase facings, then replenish.",
                "actions": [
                    {"type": "move_product", "sku": SKU, "from_slot": "A02-S03", "to_slot": "B02-S01"},
                    {"type": "change_facings", "sku": SKU, "facings": 4},
                    {"type": "replenish_shelf", "sku": SKU, "quantity": 12},
                ],
            },
        ]
    }


def _provider(body: dict[str, Any] | str | None = None, *, cycles: int = 1) -> FakeLlmProvider:
    content = json.dumps(_canonical() if body is None else body)
    responses: list[FakeLlmProvider.Response] = []
    for _ in range(cycles):
        responses.append(FakeLlmProvider.Response(tool_calls=_calls(), finish_reason="tool_calls"))
        responses.append(FakeLlmProvider.Response(content=content, finish_reason="stop"))
    return FakeLlmProvider(responses=responses)


class ContextScript:
    def __init__(self, versions: Sequence[str]) -> None:
        self._versions = list(versions)
        self.stores: list[str] = []

    def context_version(self, store_id: str) -> str:
        self.stores.append(store_id)
        if not self._versions:
            raise RuntimeError("context script exhausted")
        return self._versions.pop(0)


class UnusedContext:
    def context_version(self, store_id: str) -> str:
        raise AssertionError(f"context source called for {store_id}")


class SeenContext:
    def __init__(self) -> None:
        self.versions: list[list[str]] = []

    def score(self, decisions: Sequence[Decision]) -> list[Decision]:
        self.versions.append([item.context_version for item in decisions])
        return list(decisions)


def _start(correlation_id: str = CORRELATION) -> InvestigationStart:
    event = StoreEvent(
        event_id="evt-p017-weekend",
        correlation_id=correlation_id,
        event_type="sale.completed",
        store_id=STORE,
        sku=SKU,
        quantity=1,
        occurred_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        source="synthetic-pos",
    )
    return InvestigationStart(investigation_id=f"inv-{event.event_id}", event=event)


def _decision(
    version: str = "1",
    actions: Sequence[Any] | None = None,
    *,
    correlation_id: str = CORRELATION,
    decision_id: str = STALE_ID,
) -> Decision:
    chosen = [ReplenishShelf(sku=SKU, quantity=12)] if actions is None else list(actions)
    return Decision(
        decision_id=decision_id,
        agent_id="retailtwin-planner",
        context_version=CONTEXT,
        context_timestamp=NOW,
        evidence=[
            EvidenceBundle(
                bundle_id=f"bundle-{correlation_id}-{SKU}-stale",
                provenance="tool-registry",
                source="investigator",
                entity_versions={SKU: version},
                collected_at=NOW,
                freshness=NOW,
                store_id=STORE,
                correlation_id=correlation_id,
                is_sufficient=True,
            )
        ],
        proposed_actions=chosen,
        simulation_id=None,
        expected_impact=ExpectedImpact(kpi_score=UNSCORED_IMPACT, description="stale replenishment"),
    )


def _authorizer(twin: Any) -> NoStaleCommit:
    return NoStaleCommit(
        DecisionContextGuard(twin, clock=lambda: NOW),
        InMemoryGuardAudit(),
        clock=lambda: NOW,
    )


def _run(
    decision: Decision,
    twin: Any,
    provider: LlmProvider,
    commit: CommitPort,
    *,
    start: InvestigationStart | None = None,
    simulate: SimulationPort | None = None,
    contexts: ContextVersionSource | None = None,
    max_refreshes: int | None = 1,
) -> ReplanResult:
    return asyncio.run(
        replan(
            decision,
            start or _start(),
            authorizer=_authorizer(twin),
            provider=provider,
            registry=_registry(twin),
            commit=commit,
            contexts=contexts if contexts is not None else ContextScript([NEXT]),
            simulate=simulate,
            max_refreshes=max_refreshes,
            clock=lambda: NOW,
        )
    )


def _replan_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "retailtwin_api.agents.orchestrator.replan"
    ]


def test_stale_flagship_recovers_to_one_new_commit(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    twin = _repo()
    before = twin.get_inventory(STORE, SKU)
    assert before is not None
    stored = before.model_dump()
    decision = _decision()
    original = decision.model_dump(mode="json")
    provider = _provider()
    spy = Spy()
    contexts = ContextScript([NEXT])

    result = _run(decision, twin, provider, spy, contexts=contexts)

    assert result.status is ReplanStatus.COMMITTED
    assert result.verdict is not None and result.verdict.value == "ALLOW"
    assert result.reason_code == ALLOWED
    assert result.context_version == NEXT
    assert result.refresh_count == 1
    assert result.correlation_id == CORRELATION
    assert result.committed_decision_id == f"plan-{CORRELATION}-{SKU}-1"
    assert result.committed_decision_id != decision.decision_id
    assert decision.model_dump(mode="json") == original
    assert len(spy.decisions) == 1
    committed = spy.decisions[0]
    assert committed is not decision
    assert committed.decision_id == result.committed_decision_id
    assert committed.proposed_actions == [ReplenishShelf(sku=SKU, quantity=12)]
    assert committed.simulation_id is None
    assert committed.expected_impact.kpi_score == UNSCORED_IMPACT
    assert committed.context_version == NEXT
    assert decision.context_version == CONTEXT
    assert contexts.stores == [STORE]
    assert committed.evidence[0].correlation_id == CORRELATION
    assert committed.evidence[0].entity_versions == {SKU: "2"}
    binding = spy.bindings[0]
    assert binding.decision_id == committed.decision_id
    assert binding.store_id == STORE
    assert binding.entity_versions == {SKU: 2}
    assert provider.call_count == 2
    assert [request.metadata["correlation_id"] for request in provider.call_history] == [CORRELATION, CORRELATION]
    assert provider.call_history[0].metadata["investigation_id"] == "inv-evt-p017-weekend"
    assert provider.call_history[0].tools
    assert provider.call_history[1].structured_output is not None
    assert provider.call_history[1].structured_output.name == "candidate_plans"
    assert twin.get_inventory(STORE, SKU) is not None
    assert twin.get_inventory(STORE, SKU).model_dump() == stored
    assert any(CORRELATION in message for message in _replan_messages(caplog))


def test_retry_limit_stops_without_a_commit() -> None:
    inner = _repo(live_version=1)
    twin = AdvancingTwin(inner)
    decision = _decision()
    original = decision.model_dump(mode="json")
    provider = _provider()
    spy = Spy()
    contexts = ContextScript([NEXT, LATER])
    seen = SeenContext()

    result = _run(decision, twin, provider, spy, simulate=seen, contexts=contexts)

    assert result.status is ReplanStatus.RETRY_LIMIT
    assert result.verdict is not None and result.verdict.value == "REFRESH_REQUIRED"
    assert result.reason_code == VERSION_STALE
    assert result.context_version == NEXT
    assert result.decision_id == f"plan-{CORRELATION}-{SKU}-1"
    assert result.refresh_count == 1
    assert seen.versions == [[NEXT, NEXT, NEXT]]
    assert contexts.stores == [STORE]
    assert result.committed_decision_id is None
    assert spy.decisions == []
    assert provider.call_count == 2
    assert decision.model_dump(mode="json") == original
    stored = inner.get_inventory(STORE, SKU)
    assert stored is not None
    assert stored.version == 1
    assert stored.shelf_quantity == 8
    assert stored.backroom_quantity == 54


def test_recheck_at_the_bound_discards_the_binding() -> None:
    inner = _repo()
    twin = ShiftAfter(inner)
    provider = Boom()
    spy = Spy()

    result = _run(
        _decision(version="2"),
        twin,
        provider,
        spy,
        contexts=UnusedContext(),
        max_refreshes=0,
    )

    assert result.status is ReplanStatus.RETRY_LIMIT
    assert result.reason_code == VERSION_STALE
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert result.committed_decision_id is None
    assert spy.decisions == []
    assert provider.calls == 0
    stored = inner.get_inventory(STORE, SKU)
    assert stored is not None and stored.version == 2


def test_decision_without_evidence_does_not_refresh() -> None:
    provider = Boom()
    spy = Spy()
    decision = _decision("1").model_copy(update={"evidence": []})

    result = _run(decision, _repo(live_version=1), provider, spy, contexts=UnusedContext())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == LINEAGE_MISMATCH
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert spy.decisions == []
    assert provider.calls == 0


def test_recheck_discards_the_stale_binding_and_commits_the_new_decision() -> None:
    inner = _repo()
    twin = ShiftAfter(inner)
    decision = _decision(version="2")
    provider = _provider()
    spy = Spy()

    contexts = ContextScript([NEXT])
    result = _run(decision, twin, provider, spy, contexts=contexts)

    assert result.status is ReplanStatus.COMMITTED
    assert result.refresh_count == 1
    assert result.context_version == NEXT
    assert result.committed_decision_id == f"plan-{CORRELATION}-{SKU}-1"
    assert result.committed_decision_id != decision.decision_id
    assert decision.context_version == CONTEXT
    assert contexts.stores == [STORE]
    assert spy.decisions[0].context_version == NEXT
    assert len(spy.bindings) == 1
    assert spy.bindings[0].entity_versions == {SKU: 3}
    assert spy.bindings[0].decision_id == result.committed_decision_id
    stored = inner.get_inventory(STORE, SKU)
    assert stored is not None and stored.version == 2


def test_provider_failure_does_not_commit_or_retry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    provider = Boom()
    spy = Spy()
    decision = _decision()

    result = _run(decision, _repo(), provider, spy, contexts=UnusedContext())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == PROVIDER_FAILED
    assert result.context_version == CONTEXT
    assert result.refresh_count == 1
    assert result.committed_decision_id is None
    assert spy.decisions == []
    assert provider.calls == 1
    assert "secret" not in result.reason_code
    assert all("secret" not in message for message in _replan_messages(caplog))


def test_invalid_plan_is_terminal() -> None:
    provider = _provider("not-json")
    spy = Spy()
    contexts = ContextScript([NEXT])

    result = _run(_decision(), _repo(), provider, spy, contexts=contexts)

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == INVALID_OUTPUT
    assert result.context_version == CONTEXT
    assert result.refresh_count == 1
    assert spy.decisions == []
    assert provider.call_count == 2
    assert contexts.stores == [STORE]


def test_deny_does_not_refresh() -> None:
    provider = Boom()
    spy = Spy()
    decision = _decision("1", [ReplenishShelf(sku=SKU, quantity=80)])

    result = _run(decision, _repo(live_version=1), provider, spy, contexts=UnusedContext())

    assert result.status is ReplanStatus.DENIED
    assert result.reason_code == INFEASIBLE_ACTION
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert spy.decisions == []
    assert provider.calls == 0


def test_human_review_does_not_refresh() -> None:
    provider = Boom()
    spy = Spy()
    decision = _decision("1", [ReplenishShelf(sku=SKU, quantity=201)])

    result = _run(decision, _repo(live_version=1, backroom=250), provider, spy, contexts=UnusedContext())

    assert result.status is ReplanStatus.HUMAN_REVIEW
    assert result.reason_code == POLICY_THRESHOLD
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert spy.decisions == []
    assert provider.calls == 0


def test_fresh_decision_commits_without_refresh() -> None:
    provider = Boom()
    spy = Spy()
    decision = _decision("1")

    result = _run(decision, _repo(live_version=1), provider, spy, contexts=UnusedContext())

    assert result.status is ReplanStatus.COMMITTED
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert result.committed_decision_id == decision.decision_id
    assert [item.decision_id for item in spy.decisions] == [decision.decision_id]
    assert provider.calls == 0


def test_infeasible_candidate_falls_through_to_the_next() -> None:
    body = {
        "candidates": [
            {
                "reason": "Move P017 to B02-S01.",
                "actions": [
                    {"type": "move_product", "sku": SKU, "from_slot": "A02-S03", "to_slot": "B02-S01"}
                ],
            },
            {
                "reason": "Replenish P017 from the backroom.",
                "actions": [{"type": "replenish_shelf", "sku": SKU, "quantity": 12}],
            },
        ]
    }
    provider = _provider(body)
    spy = Spy()

    result = _run(_decision(), _repo(occupant=True), provider, spy)

    assert result.status is ReplanStatus.COMMITTED
    assert result.refresh_count == 1
    assert result.committed_decision_id == f"plan-{CORRELATION}-{SKU}-2"
    assert spy.decisions[0].proposed_actions == [ReplenishShelf(sku=SKU, quantity=12)]
    assert provider.call_count == 2


def test_simulation_port_picks_the_higher_score_without_inventing_one() -> None:
    class Scorer:
        def __init__(self) -> None:
            self.seen: list[float] = []

        def score(self, decisions: Sequence[Decision]) -> list[Decision]:
            self.seen = [item.expected_impact.kpi_score for item in decisions]
            scores = (0.07, 0.12, 0.09)
            return [
                item.model_copy(
                    update={
                        "simulation_id": f"sim-{CORRELATION}",
                        "expected_impact": ExpectedImpact(
                            kpi_score=score,
                            description=item.expected_impact.description,
                        ),
                    }
                )
                for item, score in zip(decisions, scores, strict=True)
            ]

    scorer = Scorer()
    spy = Spy()
    result = _run(_decision(), _repo(), _provider(), spy, simulate=scorer)

    assert scorer.seen == [UNSCORED_IMPACT, UNSCORED_IMPACT, UNSCORED_IMPACT]
    assert result.committed_decision_id == f"plan-{CORRELATION}-{SKU}-2"
    committed = spy.decisions[0]
    assert committed.expected_impact.kpi_score == 0.12
    assert committed.simulation_id == f"sim-{CORRELATION}"
    assert committed.context_version == NEXT
    assert result.context_version == NEXT
    assert committed.proposed_actions == [
        ChangeFacings(sku=SKU, facings=4),
        ReplenishShelf(sku=SKU, quantity=12),
    ]


def test_simulation_failure_does_not_commit(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    class Broken:
        def score(self, decisions: Sequence[Decision]) -> Sequence[Decision]:
            raise RuntimeError("secret")

    spy = Spy()
    result = _run(_decision(), _repo(), _provider(), spy, simulate=Broken())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == SIMULATION_FAILED
    assert result.refresh_count == 1
    assert spy.decisions == []
    assert all("secret" not in message for message in _replan_messages(caplog))


def test_empty_simulation_does_not_commit() -> None:
    class Empty:
        def score(self, decisions: Sequence[Decision]) -> list[Decision]:
            return []

    spy = Spy()
    result = _run(_decision(), _repo(), _provider(), spy, simulate=Empty())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == EMPTY_PLAN
    assert spy.decisions == []


def test_simulation_lineage_mismatch_does_not_commit() -> None:
    class Drift:
        def score(self, decisions: Sequence[Decision]) -> list[Decision]:
            bundle = decisions[0].evidence[0].model_copy(update={"correlation_id": "other-run"})
            return [decisions[0].model_copy(update={"evidence": [bundle]})]

    spy = Spy()
    result = _run(_decision(), _repo(), _provider(), spy, simulate=Drift())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == LINEAGE_MISMATCH
    assert spy.decisions == []


def test_provider_name_does_not_change_the_outcome() -> None:
    class OpenAICompatible(FakeLlmProvider):
        pass

    class VertexGemini(FakeLlmProvider):
        pass

    committed: list[str] = []
    for factory in (OpenAICompatible, VertexGemini):
        provider = factory(
            responses=[
                FakeLlmProvider.Response(tool_calls=_calls(), finish_reason="tool_calls"),
                FakeLlmProvider.Response(content=json.dumps(_canonical()), finish_reason="stop"),
            ]
        )
        spy = Spy()
        result = _run(_decision(), _repo(), provider, spy)
        assert result.status is ReplanStatus.COMMITTED
        assert result.refresh_count == 1
        assert result.committed_decision_id == f"plan-{CORRELATION}-{SKU}-1"
        assert [item.decision_id for item in spy.decisions] == [result.committed_decision_id]
        committed.append(result.committed_decision_id or "")
    assert committed[0] == committed[1]


def test_zero_refresh_bound_stops_before_the_provider() -> None:
    provider = Boom()
    spy = Spy()

    result = _run(_decision(), _repo(), provider, spy, contexts=UnusedContext(), max_refreshes=0)

    assert result.status is ReplanStatus.RETRY_LIMIT
    assert result.reason_code == VERSION_STALE
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert spy.decisions == []
    assert provider.calls == 0


def test_env_zero_stops_before_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_REFRESHES_ENV, "0")
    provider = Boom()
    spy = Spy()

    result = _run(_decision(), _repo(), provider, spy, contexts=UnusedContext(), max_refreshes=None)

    assert result.status is ReplanStatus.RETRY_LIMIT
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert provider.calls == 0
    assert spy.decisions == []


def test_refresh_bound_rejects_a_bad_value(monkeypatch: pytest.MonkeyPatch) -> None:
    assert max_refreshes_from_env({}) == 1
    assert max_refreshes_from_env({MAX_REFRESHES_ENV: " "}) == 1
    assert max_refreshes_from_env({MAX_REFRESHES_ENV: "2"}) == 2
    assert max_refreshes_from_env({MAX_REFRESHES_ENV: "0"}) == 0
    with pytest.raises(ReplanConfigError):
        max_refreshes_from_env({MAX_REFRESHES_ENV: "nope"})
    monkeypatch.setenv(MAX_REFRESHES_ENV, "-3")
    provider = Boom()
    with pytest.raises(ReplanConfigError):
        _run(_decision(), _repo(), provider, Spy(), max_refreshes=None)
    assert provider.calls == 0
    with pytest.raises(ReplanConfigError):
        _run(_decision(), _repo(), provider, Spy(), max_refreshes=-1)


def test_lineage_mismatch_does_not_authorize() -> None:
    provider = Boom()
    spy = Spy()
    decision = _decision("1")

    result = _run(
        decision,
        _repo(live_version=1),
        provider,
        spy,
        start=_start("other-run"),
        contexts=UnusedContext(),
    )

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == LINEAGE_MISMATCH
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert spy.decisions == []
    assert provider.calls == 0


def test_commit_failure_does_not_refresh(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    provider = Boom()
    commit = RaisingCommit()
    decision = _decision("1")

    result = _run(decision, _repo(live_version=1), provider, commit, contexts=UnusedContext())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == COMMIT_FAILED
    assert result.context_version == CONTEXT
    assert result.refresh_count == 0
    assert commit.ids == [decision.decision_id]
    assert provider.calls == 0
    assert all("secret" not in message for message in _replan_messages(caplog))


def test_second_refresh_reads_a_new_context_version() -> None:
    inner = _repo()
    twin = StepTwin(inner, hold=2)
    decision = _decision()
    original = decision.model_dump(mode="json")
    contexts = ContextScript([NEXT, LATER])
    seen = SeenContext()
    spy = Spy()

    result = _run(
        decision,
        twin,
        _provider(cycles=2),
        spy,
        simulate=seen,
        contexts=contexts,
        max_refreshes=2,
    )

    assert result.status is ReplanStatus.COMMITTED
    assert result.refresh_count == 2
    assert result.context_version == LATER
    assert result.committed_decision_id == f"plan-{CORRELATION}-{SKU}-1"
    assert contexts.stores == [STORE, STORE]
    assert seen.versions == [[NEXT, NEXT, NEXT], [LATER, LATER, LATER]]
    assert CONTEXT not in {version for batch in seen.versions for version in batch}
    committed = spy.decisions[0]
    assert committed.context_version == LATER
    assert committed.evidence[0].entity_versions == {SKU: "3"}
    assert spy.bindings[0].entity_versions == {SKU: 3}
    assert decision.model_dump(mode="json") == original
    stored = inner.get_inventory(STORE, SKU)
    assert stored is not None and stored.version == 2


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_unusable_context_version_does_not_plan(raw: object) -> None:
    class Port:
        def __init__(self) -> None:
            self.stores: list[str] = []

        def context_version(self, store_id: str) -> str:
            self.stores.append(store_id)
            return raw  # type: ignore[return-value]

    provider = _provider()
    spy = Spy()
    port = Port()

    result = _run(_decision(), _repo(), provider, spy, contexts=port)

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == CONTEXT_UNAVAILABLE
    assert result.context_version is None
    assert result.refresh_count == 1
    assert result.committed_decision_id is None
    assert spy.decisions == []
    assert provider.call_count == 1
    assert port.stores == [STORE]


def test_context_source_failure_does_not_plan(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    class Port:
        def context_version(self, store_id: str) -> str:
            raise RuntimeError("secret")

    provider = _provider()
    spy = Spy()

    result = _run(_decision(), _repo(), provider, spy, contexts=Port())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == CONTEXT_UNAVAILABLE
    assert result.context_version is None
    assert result.refresh_count == 1
    assert spy.decisions == []
    assert provider.call_count == 1
    assert all("secret" not in message for message in _replan_messages(caplog))
    assert any("error_type=RuntimeError" in message for message in _replan_messages(caplog))


def test_scorer_cannot_restore_the_rejected_context_version() -> None:
    class Slide:
        def score(self, decisions: Sequence[Decision]) -> list[Decision]:
            return [item.model_copy(update={"context_version": CONTEXT}) for item in decisions]

    spy = Spy()
    result = _run(_decision(), _repo(), _provider(), spy, simulate=Slide())

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == CONTEXT_MISMATCH
    assert result.context_version == NEXT
    assert result.refresh_count == 1
    assert spy.decisions == []


def test_plan_that_keeps_the_rejected_context_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    from retailtwin_api.agents.planner.plans import plan as real_plan

    async def keep_rejected(
        bundle: Any,
        *,
        provider: LlmProvider,
        context_version: str,
        context_timestamp: datetime,
    ) -> list[Decision]:
        produced = await real_plan(
            bundle,
            provider=provider,
            context_version=context_version,
            context_timestamp=context_timestamp,
        )
        return [item.model_copy(update={"context_version": CONTEXT}) for item in produced]

    monkeypatch.setattr("retailtwin_api.agents.orchestrator.replan.plan", keep_rejected)
    seen = SeenContext()
    spy = Spy()

    result = _run(_decision(), _repo(), _provider(), spy, simulate=seen)

    assert result.status is ReplanStatus.FAILED
    assert result.reason_code == CONTEXT_MISMATCH
    assert result.context_version == NEXT
    assert result.refresh_count == 1
    assert spy.decisions == []
    assert seen.versions == []


def test_replan_source_does_not_import_a_model_sdk_simulator_or_demo() -> None:
    source = Path(replan.__code__.co_filename).read_text(encoding="utf-8")
    lowered = source.lower()
    for banned in (
        "openai",
        "gemini",
        "vertex",
        "demo_runtime",
        "agents.simulator",
        "services.simulation",
        "services.forecasting",
        "kpi.evaluator",
        "firestore",
        "guardedexecutor",
    ):
        assert banned not in lowered, banned
