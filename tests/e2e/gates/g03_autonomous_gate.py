"""G03 Autonomous Gate (#50): a store event starts the agent without a prompt.

Runs the real API app with ``autonomy_enabled`` and publishes one deterministic
``sale.completed`` through ``POST /events``:

1. The event is accepted and handed to the Observer, which records the
   activation and returns its investigation id. No prompt is sent by anyone.
2. After the response, the investigation runs: INVESTIGATE (versioned evidence
   from the tool registry), PLAN (candidates at the current context version),
   SIMULATE (an open proposal and its Decision, ready for the guarded approve route).
3. ``GET /agent/events`` shows each stage with the event's correlation id.
4. Replaying the same event starts nothing, and the Live Twin is unchanged.

A second app whose provider fails proves the failure path: the event is still
accepted, the activity shows the failed stage, and Live is unchanged.

The model is ``FakeLlmProvider`` with scripted tool calls and plan JSON. Its first
request carries only the event handoff (ids and SKU), never a user prompt.

Usage::

    python tests/e2e/gates/g03_autonomous_gate.py --out g03-evidence.json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

if __package__ in (None, ""):  # run as a script: make ``gates`` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gates.common import SKU, STORE, captured_logs, check, gate_app, git_sha, scripted_provider, store_registry
from retailtwin_api.agents.orchestrator.autonomy import AutonomousInvestigations
from retailtwin_api.decisions import InMemoryDecisionSource
from retailtwin_api.llm.contracts import LlmProvider, LlmRequest, LlmResponse
from retailtwin_api.schemas import StoreEvent
from retailtwin_api.simulation import _build_state

GATE = "G03"
ISSUE = 50


class _FailingProvider(LlmProvider):
    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise RuntimeError("provider unavailable")


def _autonomous_app(provider: LlmProvider, observed_at: str) -> Any:
    app = gate_app()
    decisions = InMemoryDecisionSource()
    app.state.decisions = decisions
    app.state.autonomy = AutonomousInvestigations(
        provider=provider,
        registry=store_registry(app.state.store, observed_at),
        store_view=app.state.store.view,
        proposals=app.state.simulations,
        decisions=decisions,
        activity=app.state.activity,
        build_state=_build_state,
    )
    return app


def _event(run_id: str, suffix: str, at: datetime) -> StoreEvent:
    return StoreEvent(
        event_id=f"evt-{run_id}-{suffix}",
        correlation_id=f"{run_id}-{suffix}",
        event_type="sale.completed",
        store_id=STORE,
        sku=SKU,
        quantity=1,
        occurred_at=at,
        source="g03-gate",
    )


def _post(client: TestClient, event: StoreEvent) -> dict[str, Any]:
    response = client.post(
        "/events",
        content=event.model_dump_json(),
        headers={"content-type": "application/json", "X-Correlation-ID": event.correlation_id},
    )
    return {"http_status": response.status_code, **response.json()}


def _activity(client: TestClient, correlation_id: str) -> list[dict[str, Any]]:
    events = client.get("/agent/events", params={"limit": 100}).json()["events"]
    return [e for e in events if e["correlation_id"] == correlation_id]


def _run_id(given: str | None) -> str:
    return given or f"g03-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"


def run_g03(run_id: str | None = None) -> dict[str, Any]:
    """Run the gate once and return its evidence. ``evidence["result"]`` is PASS or FAIL."""
    return _run(_run_id(run_id))


def _run(run_id: str) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    checks: list[dict[str, Any]] = []
    steps: dict[str, Any] = {}
    provider = scripted_provider(cycles=1)

    with captured_logs() as logs:
        with TestClient(_autonomous_app(provider, started.isoformat())) as client:
            event = _event(run_id, "sale", started)
            live_before = client.get("/store").json()
            receipt = _post(client, event)
            activity = _activity(client, event.correlation_id)
            stages = [(e["stage"], e["status"]) for e in activity]
            simulation_id = next((e["simulation_id"] for e in activity if e.get("simulation_id")), None)
            proposal = client.get(f"/simulations/{simulation_id}").json() if simulation_id else None
            first_request = provider.call_history[0] if provider.call_history else None
            handoff = [m.content for m in first_request.messages if m.role == "user"] if first_request else []
            steps["sale"] = {
                "event": event.model_dump(mode="json"),
                "receipt": receipt,
                "activity": activity,
                "proposal": proposal,
                "first_model_request": {
                    "roles": [m.role for m in first_request.messages] if first_request else [],
                    "user_content": handoff,
                    "metadata": dict(first_request.metadata) if first_request else {},
                },
            }
            check(
                checks,
                "event_accepted_and_handed_to_the_observer",
                receipt["http_status"] == 201 and receipt.get("investigation_id") == f"inv-{event.event_id}",
                f"POST /events -> {receipt['http_status']}, investigation_id={receipt.get('investigation_id')}",
            )
            check(
                checks,
                "no_prompt_started_it",
                len(handoff) == 1
                and set(json.loads(handoff[0])) == {"correlation_id", "event_id", "sku", "store_id"}
                and dict(first_request.metadata).get("correlation_id") == event.correlation_id
                if first_request
                else False,
                f"the only user message is the event handoff {handoff[0] if handoff else None}",
            )
            check(
                checks,
                "agent_activity_began_automatically",
                stages
                == [("OBSERVE", "started"), ("INVESTIGATE", "completed"), ("PLAN", "completed"), ("SIMULATE", "completed")],
                f"GET /agent/events for {event.correlation_id}: {stages}",
            )
            check(
                checks,
                "proposal_open_for_the_guarded_route",
                bool(proposal)
                and proposal["status"] == "pending"
                and proposal["provenance"] == "autonomous-investigation"
                and proposal["correlation_id"] == event.correlation_id,
                f"simulation {simulation_id}: status={proposal and proposal['status']}",
            )
            replay = _post(client, event)
            after_replay = _activity(client, event.correlation_id)
            check(
                checks,
                "replay_starts_nothing",
                replay["http_status"] == 200
                and replay.get("duplicate") is True
                and replay.get("investigation_id") is None
                and len(after_replay) == len(activity),
                f"replay -> {replay['http_status']} duplicate={replay.get('duplicate')}; activity entries {len(activity)} -> {len(after_replay)}",
            )
            live_after = client.get("/store").json()
            check(
                checks,
                "live_twin_unchanged",
                live_after == live_before,
                f"store stayed at {live_after['context_version']}; Live changes only through POST /approve",
            )
            steps["replay"] = replay
            approved = client.post(
                f"/simulations/{simulation_id}/approve",
                json={
                    "base_context_version": client.app.state.live_context_version,  # type: ignore[attr-defined]
                    "proposal_context_version": proposal["state"]["context_version"] if proposal else "",
                },
                headers={"X-Correlation-ID": event.correlation_id},
            ).json()
            steps["approve_autonomous_proposal"] = approved
            check(
                checks,
                "autonomous_proposal_commits_only_through_the_guard",
                approved.get("verdict") == "ALLOW"
                and approved.get("status") == "committed"
                and (approved.get("guard") or {}).get("verdict") == "ALLOW",
                f"POST /approve on the autonomous proposal: verdict={approved.get('verdict')} "
                f"detail={approved.get('detail_code')} live={approved.get('live_context_version')}",
            )

        with TestClient(_autonomous_app(_FailingProvider(), started.isoformat())) as failing:
            bad = _event(run_id, "provider-down", started)
            before = failing.get("/store").json()
            receipt = _post(failing, bad)
            activity = _activity(failing, bad.correlation_id)
            stages = [(e["stage"], e["status"]) for e in activity]
            steps["failure_path"] = {"receipt": receipt, "activity": activity}
            check(
                checks,
                "provider_failure_is_visible_and_harmless",
                receipt["http_status"] == 201
                and stages == [("OBSERVE", "started"), ("INVESTIGATE", "failed")]
                and failing.get("/store").json() == before,
                f"provider down: event {receipt['http_status']}, activity {stages}, Live unchanged",
            )

    passed = all(item["passed"] for item in checks)
    return {
        "gate": GATE,
        "issue": ISSUE,
        "run_id": run_id,
        "result": "PASS" if passed else "FAIL",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "runtime": {
            "app": "retailtwin_api.main.create_app with AutonomousInvestigations",
            "trigger": "POST /events -> Observer (consume_available) -> background investigation",
            "provider": "FakeLlmProvider: scripted tool calls and plan JSON; tools execute against the Live Twin",
            "provider_calls": provider.call_count,
        },
        "checks": checks,
        "steps": steps,
        "logs": logs.records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="write the evidence JSON here")
    parser.add_argument("--run-id", help="run id; prefix of the event correlation ids")
    args = parser.parse_args(argv)
    evidence = run_g03(args.run_id)
    if args.out:
        args.out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"{GATE} run {evidence['run_id']}: {evidence['result']}")
    for item in evidence["checks"]:
        print(f"  [{'x' if item['passed'] else ' '}] {item['check']}: {item['detail']}")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
