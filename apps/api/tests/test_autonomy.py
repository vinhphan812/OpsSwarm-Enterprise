"""Autonomous investigations (G03): a new sale starts the agent without a prompt."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.agent_activity import AgentActivityLog
from retailtwin_api.agents.investigator.evidence import bind_read_port
from retailtwin_api.agents.observer.consumer import InvestigationStart
from retailtwin_api.agents.orchestrator.autonomy import (
    COMPLETED,
    FAILED,
    INSUFFICIENT,
    AutonomousInvestigations,
)
from retailtwin_api.agents.orchestrator.tool_registry import ToolRegistry, build_store_registry
from retailtwin_api.contracts import ControlStage, Decision
from retailtwin_api.decisions import InMemoryDecisionSource
from retailtwin_api.llm.contracts import LlmProvider, LlmRequest, LlmResponse, LlmToolCall
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.main import create_app
from retailtwin_api.schemas import StoreEvent
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.simulation import SimulationRepository, _build_state
from retailtwin_api.simulation_schemas import CursorParameters, PageParameters, SimulationFilters
from retailtwin_api.store import open_memory_live_store

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
SKU = "P001"


def _calls() -> list[LlmToolCall]:
    return [
        LlmToolCall(id="inv", name="get_inventory", arguments={"sku": SKU}),
        LlmToolCall(id="shelf", name="get_shelf_state", arguments={"shelf_id": "A01"}),
        LlmToolCall(id="sales", name="get_sales_history", arguments={"sku": SKU, "window_hours": 4}),
        LlmToolCall(id="forecast", name="forecast_demand", arguments={"sku": SKU, "horizon_hours": 4}),
        LlmToolCall(id="promo", name="get_promotions", arguments={"sku": SKU}),
        LlmToolCall(id="plan", name="get_planogram", arguments={}),
    ]


PLAN = json.dumps(
    {
        "candidates": [
            {"reason": "Replenish.", "actions": [{"type": "replenish_shelf", "sku": SKU, "quantity": 12}]},
            {
                "reason": "Facings then replenish.",
                "actions": [
                    {"type": "change_facings", "sku": SKU, "facings": 4},
                    {"type": "replenish_shelf", "sku": SKU, "quantity": 12},
                ],
            },
        ]
    }
)


def _provider(cycles: int = 1) -> FakeLlmProvider:
    responses: list[FakeLlmProvider.Response] = []
    for _ in range(cycles):
        responses.append(FakeLlmProvider.Response(tool_calls=_calls(), finish_reason="tool_calls"))
        responses.append(FakeLlmProvider.Response(content=PLAN, finish_reason="stop"))
    return FakeLlmProvider(responses=responses)


def _registry(store: Any, *, complete: bool = True) -> ToolRegistry:
    registry = build_store_registry(store)
    if complete:
        observed = NOW.isoformat()
        bind_read_port(registry, "get_sales_history", lambda a: {"version": "s1", "sku": a.sku, "observed_at": observed, "sales": []})
        bind_read_port(
            registry,
            "forecast_demand",
            lambda a: {"version": "forecast-demand-v1", "sku": a.sku, "forecast_units": "18", "observed_at": observed},
        )
        bind_read_port(registry, "get_promotions", lambda a: {"version": "0", "sku": a.sku, "observed_at": observed, "promotions": []})
        bind_read_port(
            registry,
            "get_planogram",
            lambda _a: {"version": "1", "observed_at": observed, "placements": [{"sku": SKU, "shelf_id": "A01", "slot_id": "A01-S01", "facings": 3}]},
        )
    return registry


def _event(event_id: str = "evt-g03-1", event_type: str = "sale.completed") -> StoreEvent:
    return StoreEvent(
        event_id=event_id,
        correlation_id=f"corr-{event_id}",
        event_type=event_type,
        store_id="store-001",
        sku=SKU,
        quantity=1,
        occurred_at=NOW,
        source="synthetic-pos",
    )


class Boom(LlmProvider):
    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise RuntimeError("secret")


class _Parts:
    def __init__(self, provider: LlmProvider, *, complete: bool = True) -> None:
        self.store = open_memory_live_store(DEFAULT_FIXTURE, "store-001")
        self.activity = AgentActivityLog()
        self.proposals = SimulationRepository(self.store.view, "store-001", activity=self.activity)
        self.decisions = InMemoryDecisionSource()
        self.autonomy = AutonomousInvestigations(
            provider=provider,
            registry=_registry(self.store, complete=complete),
            store_view=self.store.view,
            proposals=self.proposals,
            decisions=self.decisions,
            activity=self.activity,
            build_state=_build_state,
            clock=lambda: NOW,
        )

    def stages(self, correlation_id: str) -> list[tuple[str, str]]:
        return [(e.stage.value, e.status) for e in self.activity.for_correlation(correlation_id)]


def _start(event: StoreEvent) -> InvestigationStart:
    return InvestigationStart(investigation_id=f"inv-{event.event_id}", event=event)


# ─── AutonomousInvestigations ────────────────────────────────────────────────


def test_handoff_records_observe_and_queues_without_running() -> None:
    parts = _Parts(_provider())
    event = _event()

    parts.autonomy.start_investigation(_start(event))

    assert parts.autonomy.pending() == 1
    assert parts.stages(event.correlation_id) == [("OBSERVE", "started")]
    [entry] = parts.activity.for_correlation(event.correlation_id)
    assert entry.run_id == "inv-evt-g03-1" and entry.focus == SKU


def test_drain_runs_investigation_to_an_open_proposal() -> None:
    parts = _Parts(_provider())
    event = _event()
    parts.autonomy.start_investigation(_start(event))

    [run] = parts.autonomy.drain()

    assert (run.status, run.reason) == (COMPLETED, None)
    assert run.simulation_id == "sim-inv-evt-g03-1"
    assert parts.stages(event.correlation_id) == [
        ("OBSERVE", "started"),
        ("INVESTIGATE", "completed"),
        ("PLAN", "completed"),
        ("SIMULATE", "completed"),
    ]
    proposal = parts.proposals.get_simulation(run.simulation_id)
    assert proposal is not None
    assert (proposal.status, proposal.provenance, proposal.correlation_id) == ("pending", "autonomous-investigation", event.correlation_id)
    assert proposal.base_context_version == "store-001:v1"
    decision = parts.decisions.get_for_simulation(run.simulation_id)
    assert isinstance(decision, Decision)
    assert decision.decision_id == run.decision_id and decision.simulation_id == run.simulation_id
    assert decision.evidence[0].correlation_id == event.correlation_id
    assert parts.autonomy.pending() == 0


def test_investigation_never_writes_the_live_twin() -> None:
    parts = _Parts(_provider())
    before = parts.store.view()
    parts.autonomy.start_investigation(_start(_event()))
    parts.autonomy.drain()
    assert parts.store.view() == before


def test_provider_failure_is_recorded_not_raised() -> None:
    parts = _Parts(Boom())
    event = _event()
    parts.autonomy.start_investigation(_start(event))

    [run] = parts.autonomy.drain()

    assert (run.status, run.reason) == (FAILED, "provider_failed")
    assert parts.stages(event.correlation_id)[-1] == ("INVESTIGATE", "failed")
    assert "secret" not in str(parts.activity.for_correlation(event.correlation_id))


def test_missing_sources_stop_at_the_planner() -> None:
    parts = _Parts(_provider(), complete=False)
    event = _event()
    parts.autonomy.start_investigation(_start(event))

    [run] = parts.autonomy.drain()

    assert (run.status, run.reason) == (FAILED, "insufficient_evidence")
    assert parts.stages(event.correlation_id) == [
        ("OBSERVE", "started"),
        ("INVESTIGATE", INSUFFICIENT),
        ("PLAN", "failed"),
    ]


def test_unexpected_planning_error_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = _Parts(_provider())

    def broken() -> Any:
        raise RuntimeError("store down")

    monkeypatch.setattr(parts.autonomy, "_store_view", broken)
    parts.autonomy.start_investigation(_start(_event()))
    [run] = parts.autonomy.drain()
    assert (run.status, run.reason) == (FAILED, "RuntimeError")


def test_proposal_store_failure_is_recorded() -> None:
    parts = _Parts(_provider())

    class Broken:
        def record(self, run: Any) -> None:
            raise OSError("disk")

    parts.autonomy._proposals = Broken()  # type: ignore[assignment]
    event = _event()
    parts.autonomy.start_investigation(_start(event))
    [run] = parts.autonomy.drain()
    assert (run.status, run.reason) == (FAILED, "OSError")
    assert parts.stages(event.correlation_id)[-1] == ("SIMULATE", "failed")


def test_default_clock_is_utc() -> None:
    store = open_memory_live_store(DEFAULT_FIXTURE, "store-001")
    activity = AgentActivityLog()
    autonomy = AutonomousInvestigations(
        provider=_provider(),
        registry=_registry(store),
        store_view=store.view,
        proposals=SimulationRepository(store.view, "store-001", activity=activity),
        decisions=InMemoryDecisionSource(),
        activity=activity,
        build_state=_build_state,
    )
    autonomy.start_investigation(_start(_event()))
    assert activity.for_correlation("corr-evt-g03-1")[0].ts.tzinfo is not None


# ─── Activity log and repository ─────────────────────────────────────────────


def test_activity_log_pages_with_an_offset_cursor() -> None:
    log = AgentActivityLog()
    for index in range(3):
        log.record(ControlStage.OBSERVE, "started", f"c{index}", at=NOW)

    first, cursor = log.page(CursorParameters(limit=2))
    rest, end = log.page(CursorParameters(since=cursor, limit=2))

    assert [e.correlation_id for e in first] == ["c0", "c1"] and cursor == "2"
    assert [e.correlation_id for e in rest] == ["c2"] and end is None


@pytest.mark.parametrize("since", ["x", "-1"])
def test_activity_log_rejects_bad_cursors(since: str) -> None:
    with pytest.raises(ValueError):
        AgentActivityLog().page(CursorParameters(since=since))


def test_activity_entries_are_detached() -> None:
    log = AgentActivityLog()
    log.record(ControlStage.OBSERVE, "started", "c", at=NOW)
    log.page(CursorParameters())[0][0].status = "edited"
    assert log.page(CursorParameters())[0][0].status == "started"


def test_simulation_repository_lists_candidates_and_records_runs() -> None:
    store = open_memory_live_store(DEFAULT_FIXTURE, "store-001")
    repo = SimulationRepository(store.view, "store-001")
    seeded = repo.list_simulations(SimulationFilters())
    sid = seeded.simulations[0].simulation_id
    page = repo.list_candidates(sid, PageParameters())
    assert page is not None and page.total == 0
    assert repo.list_candidates("missing", PageParameters()) is None
    assert repo.list_agent_events(CursorParameters()) == ([], None)


# ─── Routes ──────────────────────────────────────────────────────────────────


@pytest.fixture
def autonomous_client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    parts_store = app.state.store
    decisions = InMemoryDecisionSource()
    app.state.decisions = decisions
    app.state.autonomy = AutonomousInvestigations(
        provider=_provider(cycles=3),
        registry=_registry(parts_store),
        store_view=parts_store.view,
        proposals=app.state.simulations,
        decisions=decisions,
        activity=app.state.activity,
        build_state=_build_state,
    )
    with TestClient(app) as client:
        yield client


def _post(client: TestClient, event: StoreEvent) -> Any:
    return client.post("/events", content=event.model_dump_json(), headers={"content-type": "application/json"})


def test_new_sale_starts_an_investigation_without_a_prompt(autonomous_client: TestClient) -> None:
    response = _post(autonomous_client, _event())

    assert response.status_code == 201
    assert response.json()["investigation_id"] == "inv-evt-g03-1"
    events = autonomous_client.get("/agent/events").json()["events"]
    assert [(e["stage"], e["status"]) for e in events] == [
        ("OBSERVE", "started"),
        ("INVESTIGATE", "completed"),
        ("PLAN", "completed"),
        ("SIMULATE", "completed"),
    ]
    assert {e["correlation_id"] for e in events} == {"corr-evt-g03-1"}
    proposal = autonomous_client.get("/simulations/sim-inv-evt-g03-1")
    assert proposal.status_code == 200 and proposal.json()["provenance"] == "autonomous-investigation"
    assert autonomous_client.get("/simulations/sim-inv-evt-g03-1/candidates").json()["total"] == 0


def test_duplicate_sale_does_not_start_a_second_investigation(autonomous_client: TestClient) -> None:
    _post(autonomous_client, _event())
    again = _post(autonomous_client, _event())

    assert again.status_code == 200 and again.json()["investigation_id"] is None
    stages = [e["stage"] for e in autonomous_client.get("/agent/events").json()["events"]]
    assert stages.count("OBSERVE") == 1


def test_non_sale_event_is_not_investigated(autonomous_client: TestClient) -> None:
    response = _post(autonomous_client, _event("evt-restock-1", event_type="inventory.adjusted"))
    assert response.status_code == 201 and response.json()["investigation_id"] is None
    assert autonomous_client.get("/agent/events").json()["events"] == []


def test_failed_handoff_still_accepts_the_event(autonomous_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(start: InvestigationStart) -> None:
        raise RuntimeError("queue full")

    monkeypatch.setattr(autonomous_client.app.state.autonomy, "start_investigation", refuse)  # type: ignore[attr-defined]
    response = _post(autonomous_client, _event())
    assert response.status_code == 201 and response.json()["investigation_id"] is None


def test_autonomy_is_off_by_default(settings: Settings) -> None:
    app = create_app(settings)
    assert app.state.autonomy is None
    with TestClient(app) as client:
        response = _post(client, _event())
        assert response.json()["investigation_id"] is None
        assert client.get("/agent/events").status_code == 200


def test_autonomy_setting_builds_the_configured_provider(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"autonomy_enabled": True}))
    assert isinstance(app.state.autonomy, AutonomousInvestigations)
    assert isinstance(app.state.decisions, InMemoryDecisionSource)


def test_agent_events_and_candidates_no_longer_fail(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        assert client.get("/agent/events").status_code == 200
        assert client.get("/simulations/sim-seed-001/candidates").status_code == 200
        assert client.get("/simulations/missing/candidates").status_code == 404


def test_misconfigured_provider_leaves_autonomy_off(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"autonomy_enabled": True, "llm_provider": "no-such-provider"}))
    assert app.state.autonomy is None
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
