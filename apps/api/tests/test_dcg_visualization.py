"""DCG visualization surfaces (#40): the Decision Context Guard card data.

The API exposes the verdict, reason, per-gate breakdown, context provenance
and commit-authorization receipt so the FE can render the DCG card without a
separate audit query. These tests cover the five contract pieces:

- ``GET /simulations/{id}`` returns the guard verdict and per-gate breakdown.
- ``GET /simulations/{id}/candidates`` mirrors the same fields per candidate.
- ``GET /agent/events`` carries ``acquired_at`` and the stage verdict.
- ``POST /simulations/{id}/approve`` returns the redeem receipt.
- A ``REFRESH_REQUIRED`` outcome reports both the base and live context
  versions, so the card can show the stale-context evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from retailtwin_api.contracts import (
    ControlStage,
    Decision,
    EvidenceBundle,
    ExpectedImpact,
    MoveProduct,
)
from retailtwin_api.decisions import InMemoryDecisionSource
from retailtwin_api.main import create_app
from retailtwin_api.schemas import ProductInventory, StoreResponse
from retailtwin_api.settings import DEFAULT_FIXTURE, Settings
from retailtwin_api.simulation_repository import InMemorySimulationRepository
from retailtwin_api.simulation_schemas import (
    AgentActivityEntry,
    CandidateKPI,
    SimulationCandidateResponse,
    SimulationDetail,
    SimulationState,
)


SIM = "sim-dcg-001"
BASE_VERSION = "store-001:v1"
LIVE_VERSION = "store-001:v1"


def _store_response() -> StoreResponse:
    return StoreResponse(
        store_id="store-001",
        context_version=LIVE_VERSION,
        version="v1",
        products=[
            ProductInventory(
                store_id="store-001",
                sku="P001",
                shelf_id="A01",
                slot_id="A01-S01",
                facings=3,
                shelf_quantity=8,
                backroom_quantity=42,
                version=1,
            )
        ],
    )


def _simulation(simulation_id: str = SIM) -> SimulationDetail:
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    return SimulationDetail(
        simulation_id=simulation_id,
        store_id="store-001",
        base_context_version=BASE_VERSION,
        status="evaluated",
        created_at=now,
        updated_at=now,
        provenance="simulation-service",
        correlation_id=f"corr-{simulation_id}",
        agent_id="planner",
        actions=[MoveProduct(sku="P001", from_slot="A01-S01", to_slot="A02-S01")],
        state=SimulationState(store=_store_response(), context_version=f"{simulation_id}:v1"),
    )


def _decision(
    simulation_id: str = SIM,
    *,
    context_version: str = BASE_VERSION,
    context_timestamp: datetime | None = None,
) -> Decision:
    # A fresh context so the freshness gate does not expire it (TTL is 120s).
    ts = context_timestamp or datetime.now(timezone.utc)
    return Decision(
        decision_id=f"dec-{simulation_id}",
        agent_id="planner",
        context_version=context_version,
        context_timestamp=ts,
        evidence=[
            EvidenceBundle(
                bundle_id=f"bundle-{simulation_id}",
                provenance="tool-registry",
                source="investigator",
                entity_versions={"P001": "1"},
                collected_at=ts,
                freshness=ts,
                store_id="store-001",
                correlation_id=f"corr-{simulation_id}",
                is_sufficient=True,
            )
        ],
        proposed_actions=[MoveProduct(sku="P001", from_slot="A01-S01", to_slot="A02-S01")],
        simulation_id=simulation_id,
        expected_impact=ExpectedImpact(kpi_score=0.1, description="closer to the entrance"),
    )


def _candidate(simulation_id: str = SIM) -> SimulationCandidateResponse:
    sim = _simulation(simulation_id)
    # The simulator binds a candidate to a decision by reusing
    # ``decision.decision_id`` as ``candidate_id`` so the candidates route can
    # identify the one the guard evaluated.
    return SimulationCandidateResponse(
        candidate_id=f"dec-{simulation_id}",
        simulation_id=simulation_id,
        proposed_actions=sim.actions,
        state=sim.state,
        kpis=[CandidateKPI(name="sales_uplift", value=2.5, unit="percent", source="d11")],
        evaluator_version="d11:v1",
        provenance="kpi-evaluator",
        created_at=sim.created_at,
    )


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key in (
        "APP_ENV",
        "API_HOST",
        "API_PORT",
        "CORS_ORIGINS",
        "STORE_ID",
        "STORE_FIXTURE_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)
    return Settings(
        _env_file=None,
        app_env="test",
        store_id="store-001",
        store_fixture_path=DEFAULT_FIXTURE,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    activity_entry = AgentActivityEntry(
        id="activity-dcg-001",
        ts=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        stage=ControlStage.GUARD,
        status="completed",
        correlation_id=f"corr-{SIM}",
        run_id="run-001",
        decision=f"dec-{SIM}",
        simulation_id=SIM,
        acquired_at=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        verdict="ALLOW",
    )
    repo = InMemorySimulationRepository(
        [_simulation()], [_candidate()], [activity_entry],
    )
    app.state.simulations = repo
    decisions = InMemoryDecisionSource()
    decisions.put(SIM, _decision())
    app.state.decisions = decisions
    app.state.live_context_version = LIVE_VERSION
    with TestClient(app) as test_client:
        yield test_client


def test_simulation_response_includes_guard_verdict(client: TestClient) -> None:
    """``GET /simulations/{id}`` surfaces the latest DCG verdict, gates and authorization."""
    response = client.get(f"/simulations/{SIM}")
    assert response.status_code == 200
    body = response.json()
    assert body["simulation_id"] == SIM
    assert body["guard_verdict"] is None  # No approval yet → no guard audit yet
    assert body["guard_reason"] is None
    assert body["guard_gates"] == []
    assert body["decision_context_version"] is None
    assert body["decision_context_timestamp"] is None
    assert body["freshness_seconds"] is None
    assert body["authorization"] == {"status": "none", "issued_at": None, "expires_at": None,
                                     "action_count": 0, "action_hashes": [], "binding_id": None}

    # Run an approval so the guard audit produces an ALLOW event with all
    # six gates. The /simulations/{id} response then surfaces it.
    approval = client.post(
        f"/simulations/{SIM}/approve",
        json={"base_context_version": BASE_VERSION, "proposal_context_version": f"{SIM}:v1"},
    ).json()
    assert approval["verdict"] == "ALLOW"
    after = client.get(f"/simulations/{SIM}").json()
    assert after["guard_verdict"] == "ALLOW"
    assert after["guard_reason"] == "ALLOWED"
    gate_ids = [row["gate_id"] for row in after["guard_gates"]]
    assert gate_ids == ["integrity", "evidence", "context", "freshness", "feasibility", "policy"]
    assert all(row["status"] == "passed" for row in after["guard_gates"])
    assert after["decision_context_version"] == BASE_VERSION
    assert after["decision_context_timestamp"] is not None
    assert after["freshness_seconds"] is not None and after["freshness_seconds"] >= 0
    # The token was consumed by the Executor, so we have no record of the
    # action hashes here. The binding id (context hash) is in the audit trail.
    assert after["authorization"]["binding_id"]  # context hash
    assert after["authorization"]["status"] in {"redeemed", "none"}


def test_candidate_response_includes_guard_breakdown(client: TestClient) -> None:
    """``GET /simulations/{id}/candidates`` binds the verdict to the evaluated candidate.

    The simulator reuses ``decision.decision_id`` as ``candidate_id``, so the
    only candidate in this fixture is the one the guard will evaluate. Before
    any guard run the DCG fields are all null (the guard has nothing to
    report). After an ALLOW the chosen candidate carries the full breakdown;
    the not_evaluated marker is reserved for alternatives the guard ran
    against a different candidate (see
    ``test_list_candidates_distinguishes_evaluated_from_not_evaluated``).
    """
    # No approval yet: every DCG field is null on every candidate.
    before = client.get(f"/simulations/{SIM}/candidates").json()
    assert before["candidates"][0]["guard_verdict"] is None
    assert before["candidates"][0]["guard_reason"] is None
    assert before["candidates"][0]["guard_gates"] == []
    assert before["candidates"][0]["authorization"] is None

    # After an approval the chosen candidate (the one whose id matches the
    # decision's decision_id) carries the full DCG breakdown. This fixture
    # only has the chosen candidate.
    client.post(
        f"/simulations/{SIM}/approve",
        json={"base_context_version": BASE_VERSION, "proposal_context_version": f"{SIM}:v1"},
    )
    after = client.get(f"/simulations/{SIM}/candidates").json()
    candidate = after["candidates"][0]
    assert candidate["guard_verdict"] == "ALLOW"
    assert candidate["guard_reason"] == "ALLOWED"
    assert [row["gate_id"] for row in candidate["guard_gates"]] == [
        "integrity", "evidence", "context", "freshness", "feasibility", "policy",
    ]
    assert all(row["status"] == "passed" for row in candidate["guard_gates"])
    assert candidate["decision_context_version"] == BASE_VERSION
    assert candidate["authorization"]["binding_id"]


def test_agent_event_response_includes_correlation_id(client: TestClient) -> None:
    """``/agent/events`` carries ``acquired_at`` and the stage verdict."""
    response = client.get("/agent/events", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["cursor"] is None
    events = body["events"]
    assert len(events) == 1
    entry = events[0]
    assert entry["stage"] == "GUARD"
    assert entry["status"] == "completed"
    assert entry["correlation_id"] == f"corr-{SIM}"
    assert entry["acquired_at"] is not None
    assert entry["acquired_at"] == "2026-10-14T12:00:00Z"
    assert entry["verdict"] == "ALLOW"
    assert entry["run_id"] == "run-001"
    assert entry["decision"] == f"dec-{SIM}"
    assert entry["simulation_id"] == SIM


def test_approve_response_includes_binding_receipt(client: TestClient) -> None:
    """``POST /simulations/{id}/approve`` returns the redeem receipt on ALLOW."""
    response = client.post(
        f"/simulations/{SIM}/approve",
        json={"base_context_version": BASE_VERSION, "proposal_context_version": f"{SIM}:v1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "ALLOW"
    assert body["reason_code"] == "APPROVED"
    assert body["status"] == "committed"
    # The binding id is the context hash the Executor committed against.
    assert body["binding_id"]
    assert body["binding_id"] == body["guard"]["context_hash"]
    # The expiry is the binding's expiry (within policy TTL, never outlives it).
    assert body["expires_at"]
    action_hashes: list[str] = body["action_hashes"]
    assert action_hashes and all(len(item) == 64 for item in action_hashes)
    # The Executor's entity_versions agree with the receipt's action hashes count.
    assert len(action_hashes) == len(body["guard"]["policy_result"]["entity_versions"])


def test_refresh_required_response_includes_context_versions(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale decision surfaces base_context_version vs live_context_version."""
    # Bump the live SKU version so the decision's evidence (read at v1)
    # is one step behind. ``upsert_inventory`` does not advance the store
    # version, so ``live_context_version`` stays at ``store-001:v1`` and
    # the route's precheck passes. The guard then refuses on the context
    # gate with VERSION_STALE.
    twin = client.app.state.live_twin  # type: ignore[attr-defined]
    current = twin.get_inventory("store-001", "P001")
    assert current is not None
    twin.upsert_inventory(current.model_copy(update={"version": 2}), expected_version=1)

    response = client.post(
        f"/simulations/{SIM}/approve",
        json={"base_context_version": BASE_VERSION, "proposal_context_version": f"{SIM}:v1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "REFRESH_REQUIRED"
    assert body["reason_code"] == "VERSION_STALE"
    assert body["status"] == "evaluated"
    # The card needs both the version the decision was built on and the
    # version Live Twin now reports, plus the gate row that failed.
    assert body["live_context_version"] == BASE_VERSION
    assert body["guard"]["policy_result"]["entity_versions"]["P001"] == "2"
    failed = [row for row in body["guard"]["policy_result"]["checks"] if not row["passed"]]
    assert failed and failed[0]["gate"] == "context"
    # The receipt is absent because no authorization was issued.
    assert body["binding_id"] is None
    assert body["expires_at"] is None
    assert body["action_hashes"] == []


# ─── Per-candidate DCG scoping (CHANGES_REQUESTED #40) ────────────────────────

EVALUATED_CANDIDATE_ID = f"dec-{SIM}"  # matches the decision's decision_id
ALT_CANDIDATE_ID_A = f"candidate-alt-A-{SIM}"
ALT_CANDIDATE_ID_B = f"candidate-alt-B-{SIM}"


def _alt_candidate(candidate_id: str) -> SimulationCandidateResponse:
    """A candidate the guard will not evaluate. Same KPIs, different id."""
    sim = _simulation()
    return SimulationCandidateResponse(
        candidate_id=candidate_id,
        simulation_id=sim.simulation_id,
        proposed_actions=sim.actions,
        state=sim.state,
        kpis=[CandidateKPI(name="sales_uplift", value=1.7, unit="percent", source="d11")],
        evaluator_version="d11:v1",
        provenance="kpi-evaluator",
        created_at=sim.created_at,
    )


@pytest.fixture
def multi_candidate_client(settings: Settings) -> Iterator[TestClient]:
    """Client with one simulation that has a chosen candidate and two alternatives.

    The chosen candidate's ``candidate_id`` matches the decision's
    ``decision_id`` (``f"dec-{SIM}"``), matching the simulator's contract. The
    two alternative candidates are not bound to any decision and must read as
    ``not_evaluated`` once the guard has run.
    """
    app = create_app(settings)
    activity_entry = AgentActivityEntry(
        id="activity-dcg-multi-001",
        ts=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        stage=ControlStage.GUARD,
        status="completed",
        correlation_id=f"corr-{SIM}",
        run_id="run-001",
        decision=f"dec-{SIM}",
        simulation_id=SIM,
        acquired_at=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        verdict="ALLOW",
    )
    candidates = [
        _alt_candidate(ALT_CANDIDATE_ID_A),  # alternatives first
        _candidate(),
        _alt_candidate(ALT_CANDIDATE_ID_B),
    ]
    repo = InMemorySimulationRepository([_simulation()], candidates, [activity_entry])
    app.state.simulations = repo
    decisions = InMemoryDecisionSource()
    decisions.put(SIM, _decision())
    app.state.decisions = decisions
    app.state.live_context_version = LIVE_VERSION
    with TestClient(app) as test_client:
        yield test_client


def test_list_candidates_distinguishes_evaluated_from_not_evaluated(
    multi_candidate_client: TestClient,
) -> None:
    """The verdict is bound only to the candidate the guard actually evaluated.

    Regression test for the CHANGES_REQUESTED review on PR #252: the previous
    implementation applied the simulation-level verdict to every candidate in
    the response. The route now binds the verdict to the candidate whose
    ``candidate_id`` matches the decision's ``decision_id``; every other
    candidate reports ``verdict=None``, ``reason="not_evaluated"``,
    ``gates=[]`` and ``authorization=None``.
    """
    # Run the guard exactly once, against the chosen candidate.
    approval = multi_candidate_client.post(
        f"/simulations/{SIM}/approve",
        json={"base_context_version": BASE_VERSION, "proposal_context_version": f"{SIM}:v1"},
    )
    assert approval.status_code == 200
    assert approval.json()["verdict"] == "ALLOW"

    body = multi_candidate_client.get(f"/simulations/{SIM}/candidates").json()
    by_id: dict[str, dict[str, object]] = {c["candidate_id"]: c for c in body["candidates"]}
    assert set(by_id) == {EVALUATED_CANDIDATE_ID, ALT_CANDIDATE_ID_A, ALT_CANDIDATE_ID_B}

    # The chosen candidate carries the full DCG breakdown + an authorization.
    chosen = by_id[EVALUATED_CANDIDATE_ID]
    assert chosen["guard_verdict"] == "ALLOW"
    assert chosen["guard_reason"] == "ALLOWED"
    assert [row["gate_id"] for row in chosen["guard_gates"]] == [
        "integrity", "evidence", "context", "freshness", "feasibility", "policy",
    ]
    assert all(row["status"] == "passed" for row in chosen["guard_gates"])
    assert chosen["decision_context_version"] == BASE_VERSION
    assert chosen["decision_context_timestamp"] is not None
    assert chosen["freshness_seconds"] is not None and chosen["freshness_seconds"] >= 0
    assert chosen["authorization"] is not None
    assert chosen["authorization"]["binding_id"]

    # Every alternative reads as not_evaluated: the FE card must never paint
    # an authorization on a plan that was never authorized.
    for alt_id in (ALT_CANDIDATE_ID_A, ALT_CANDIDATE_ID_B):
        alt = by_id[alt_id]
        assert alt["guard_verdict"] is None, alt
        assert alt["guard_reason"] == "not_evaluated", alt
        assert alt["guard_gates"] == [], alt
        assert alt["decision_context_version"] is None, alt
        assert alt["decision_context_timestamp"] is None, alt
        assert alt["freshness_seconds"] is None, alt
        assert alt["authorization"] is None, alt


def test_list_candidates_with_no_guard_run_returns_all_not_evaluated(
    settings: Settings,
) -> None:
    """Before any guard run every candidate reports the all-null DCG defaults.

    The review review rejected the previous behaviour because it painted the
    same simulation-level verdict on every candidate. The flip side is that
    before the guard has run at all there is no verdict and no authorization
    for any candidate, so the card should report a null verdict everywhere.
    """
    app = create_app(settings)
    candidates = [
        _alt_candidate(ALT_CANDIDATE_ID_A),
        _candidate(),
        _alt_candidate(ALT_CANDIDATE_ID_B),
    ]
    repo = InMemorySimulationRepository([_simulation()], candidates, [])
    app.state.simulations = repo
    decisions = InMemoryDecisionSource()
    decisions.put(SIM, _decision())
    app.state.decisions = decisions
    app.state.live_context_version = LIVE_VERSION

    with TestClient(app) as client:
        body = client.get(f"/simulations/{SIM}/candidates").json()

    assert [c["candidate_id"] for c in body["candidates"]] == [
        ALT_CANDIDATE_ID_A, EVALUATED_CANDIDATE_ID, ALT_CANDIDATE_ID_B,
    ]
    for candidate in body["candidates"]:
        assert candidate["guard_verdict"] is None, candidate
        assert candidate["guard_reason"] is None, candidate
        assert candidate["guard_gates"] == [], candidate
        assert candidate["decision_context_version"] is None, candidate
        assert candidate["decision_context_timestamp"] is None, candidate
        assert candidate["freshness_seconds"] is None, candidate
        assert candidate["authorization"] is None, candidate