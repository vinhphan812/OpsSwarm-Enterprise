"""One correlated agent-action trace, including the flagship replenishment."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from retailtwin_api.audit.trail import (
    AUDIT_TABLE,
    TRACE_COLUMNS,
    AuditConflict,
    AuditOutcome,
    AuditRecord,
    AuditRejected,
    AuditStage,
    AuditUnavailable,
    BigQueryAuditLog,
    InMemoryAuditLog,
    record_trace,
    records_from_decision,
    trace,
    trace_sql,
)
from retailtwin_api.backbone import BackboneConfig, BackboneError, format_occurred_at
from retailtwin_api.contracts import Decision, EvidenceBundle, ExpectedImpact, ReplenishShelf
from retailtwin_api.firestore_twin import InMemoryTwinRepository, InventorySeed
from retailtwin_api.guard.decision_context_guard import (
    ALLOWED,
    INFEASIBLE_ACTION,
    DecisionContextGuard,
    InMemoryGuardAudit,
    NoStaleCommit,
)

CORRELATION = "run-weekend-demand-surge-1"
STORE = "store-001"
SKU = "P017"
TRIGGER = "evt-p017-weekend"
DECISION_ID = f"plan-{CORRELATION}-{SKU}-1"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _decision(
    *,
    version: str = "2",
    quantity: int = 12,
    description: str = "Replenish P017 from the backroom.",
    backroom_note: str = "stale replenishment",
) -> Decision:
    del backroom_note
    return Decision(
        decision_id=DECISION_ID,
        agent_id="retailtwin-planner",
        context_version=f"{STORE}:v2",
        context_timestamp=NOW,
        evidence=[
            EvidenceBundle(
                bundle_id=f"bundle-{CORRELATION}-{SKU}",
                provenance="tool-registry",
                source="investigator",
                entity_versions={SKU: version},
                collected_at=NOW,
                freshness=NOW,
                store_id=STORE,
                correlation_id=CORRELATION,
                is_sufficient=True,
            )
        ],
        proposed_actions=[ReplenishShelf(sku=SKU, quantity=quantity)],
        simulation_id=None,
        expected_impact=ExpectedImpact(kpi_score=-1.0, description=description),
    )


def _twin(backroom: int = 54, version: int = 2) -> InMemoryTwinRepository:
    repo = InMemoryTwinRepository()
    repo.seed(
        STORE,
        "v1",
        [
            InventorySeed(
                sku=SKU,
                shelf_id="A02",
                slot_id="A02-S03",
                facings=2,
                shelf_quantity=8,
                backroom_quantity=backroom,
            )
        ],
    )
    if version != 1:
        doc = repo.get_inventory(STORE, SKU)
        assert doc is not None
        repo.upsert_inventory(doc.model_copy(update={"version": version}), expected_version=1)
    return repo


def _guard(decision: Decision, twin: InMemoryTwinRepository) -> tuple[str, str]:
    authorizer = NoStaleCommit(
        DecisionContextGuard(twin, clock=lambda: NOW),
        InMemoryGuardAudit(),
        clock=lambda: NOW,
    )
    verdict, _binding = authorizer.authorize(decision)
    return verdict.verdict.value, verdict.reason_code


def _flagship_records() -> list[AuditRecord]:
    decision = _decision()
    verdict, reason = _guard(decision, _twin())
    return records_from_decision(
        decision,
        trigger=TRIGGER,
        recorded_at=NOW,
        guard_verdict=verdict,
        guard_reason=reason,
        execution=[(f"{DECISION_ID}:0", "applied", None)],
        observed_status="VERIFIED",
        observed_reason="inventory_matches",
    )


def test_flagship_trace_queries_by_correlation_id() -> None:
    decision = _decision()
    original = decision.model_dump(mode="json")
    store = InMemoryAuditLog()

    outcome = record_trace(store, _flagship_records())
    rows = trace(store, CORRELATION)

    assert outcome is AuditOutcome.INSERTED
    assert decision.model_dump(mode="json") == original
    assert [row.stage for row in rows] == [
        AuditStage.TRIGGER,
        AuditStage.EVIDENCE,
        AuditStage.DECISION,
        AuditStage.GUARD,
        AuditStage.EXECUTION,
        AuditStage.OBSERVED,
    ]
    assert {row.correlation_id for row in rows} == {CORRELATION}
    assert rows[0].trigger_ref == TRIGGER
    assert rows[0].decision_id == ""
    assert rows[1].evidence_refs == json.dumps([f"bundle-{CORRELATION}-{SKU}:{SKU}=2"])
    assert rows[2].reason_summary == "Replenish P017 from the backroom."
    assert rows[2].predicted_impact == "-1.0"
    assert rows[2].simulation_id == ""
    assert json.loads(rows[2].tool_params) == [{"quantity": 12, "sku": SKU, "type": "replenish_shelf"}]
    assert rows[3].guard_verdict == "ALLOW"
    assert rows[3].guard_reason == ALLOWED
    assert rows[4].action_id == f"{DECISION_ID}:0"
    assert rows[4].execution_status == "applied"
    assert rows[4].sku == SKU
    assert rows[5].observed_status == "VERIFIED"
    assert "chain_of_thought" not in json.dumps([row.model_dump(mode="json") for row in rows])


def test_denied_trace_stops_before_execution() -> None:
    decision = _decision(version="1", quantity=80)
    verdict, reason = _guard(decision, _twin(version=1))
    store = InMemoryAuditLog()
    records = records_from_decision(
        decision,
        trigger=TRIGGER,
        recorded_at=NOW,
        guard_verdict=verdict,
        guard_reason=reason,
    )

    assert record_trace(store, records) is AuditOutcome.INSERTED
    rows = trace(store, CORRELATION)
    assert [row.stage for row in rows] == [
        AuditStage.TRIGGER,
        AuditStage.EVIDENCE,
        AuditStage.DECISION,
        AuditStage.GUARD,
    ]
    assert rows[3].guard_verdict == "DENY"
    assert rows[3].guard_reason == INFEASIBLE_ACTION
    assert record_trace(store, records) is AuditOutcome.DUPLICATE
    assert len(trace(store, CORRELATION)) == 4


def test_conflicting_payload_does_not_replace_the_trace() -> None:
    store = InMemoryAuditLog()
    records = _flagship_records()
    record_trace(store, records)
    changed = records[2].model_copy(update={"reason_summary": "A different summary."})

    with pytest.raises(AuditConflict):
        record_trace(store, [changed])

    assert trace(store, CORRELATION)[2].reason_summary == "Replenish P017 from the backroom."


def test_trace_rejects_a_transcript_or_a_naive_clock() -> None:
    with pytest.raises(AuditRejected):
        records_from_decision(
            _decision(description="x" * 281),
            trigger=TRIGGER,
            recorded_at=NOW,
            guard_verdict="ALLOW",
            guard_reason=ALLOWED,
        )
    with pytest.raises(AuditRejected):
        records_from_decision(
            _decision(description="line\nbreak"),
            trigger=TRIGGER,
            recorded_at=NOW,
            guard_verdict="ALLOW",
            guard_reason=ALLOWED,
        )
    with pytest.raises(AuditRejected):
        records_from_decision(
            _decision(),
            trigger=TRIGGER,
            recorded_at=NOW.replace(tzinfo=None),
            guard_verdict="ALLOW",
            guard_reason=ALLOWED,
        )
    with pytest.raises(AuditRejected):
        records_from_decision(
            _decision(),
            trigger=TRIGGER,
            recorded_at=NOW,
            guard_verdict="ALLOW",
            guard_reason=ALLOWED,
            observed_status="VERIFIED",
        )
    with pytest.raises(AuditRejected):
        records_from_decision(
            _decision(),
            trigger=TRIGGER,
            recorded_at=NOW,
            guard_verdict="ALLOW",
            guard_reason=ALLOWED,
            execution=[("other", "applied", None)],
        )
    with pytest.raises(AuditRejected):
        record_trace(InMemoryAuditLog(), [])


class _Runner:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> str:
        self.calls.append(args)
        if not self._responses:
            return ""
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


def test_bigquery_insert_and_trace_use_the_audit_table() -> None:
    records = _flagship_records()
    runner = _Runner(["[]"])
    log = BigQueryAuditLog(BackboneConfig(), runner)

    assert log.record(records) is AuditOutcome.INSERTED

    select = runner.calls[0][-1]
    assert AUDIT_TABLE in select
    assert "correlation_id = @correlation_id" in select
    assert f"`retailtwin-ai-511002.retailtwin.{AUDIT_TABLE}`" in select
    inserts = [call[-1] for call in runner.calls[1:]]
    assert len(inserts) == len(records)
    assert all("INSERT INTO" in sql and "NOT EXISTS" in sql for sql in inserts)
    assert all("CURRENT_TIMESTAMP()" in sql for sql in inserts)


def test_bigquery_replay_is_a_duplicate() -> None:
    records = _flagship_records()
    payload = json.dumps([_stored(row) for row in records])
    runner = _Runner([payload, payload])
    log = BigQueryAuditLog(BackboneConfig(), runner)

    assert log.record(records) is AuditOutcome.DUPLICATE
    assert [row.record_id for row in trace(log, CORRELATION)] == [row.record_id for row in records]
    assert len(runner.calls) == 2


def test_bigquery_conflict_does_not_insert(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    records = _flagship_records()
    stored = [_stored(row) for row in records]
    stored[2]["reason_summary"] = "secret summary"
    runner = _Runner([json.dumps(stored)])
    log = BigQueryAuditLog(BackboneConfig(), runner)

    with pytest.raises(AuditConflict) as caught:
        log.record(records)

    assert "secret" not in str(caught.value)
    assert len(runner.calls) == 1
    assert all("secret" not in message for message in _messages(caplog))


def test_existing_job_is_joined_and_a_failed_job_stays_closed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    record = _flagship_records()[0]
    joined = _Runner(
        [
            "[]",
            BackboneError("Already Exists: secret"),
            "",
            json.dumps({"status": {"state": "DONE"}}),
        ]
    )
    assert BigQueryAuditLog(BackboneConfig(), joined).record([record]) is AuditOutcome.INSERTED
    assert any("wait" in call for call in joined.calls[2])
    assert all("secret" not in message for message in _messages(caplog))

    failed = _Runner(
        [
            "[]",
            BackboneError("Already Exists: secret"),
            "",
            json.dumps({"status": {"state": "DONE", "errorResult": {"message": "secret"}}}),
        ]
    )
    with pytest.raises(AuditUnavailable) as caught:
        BigQueryAuditLog(BackboneConfig(), failed).record([record])
    assert str(caught.value) == "The audit table could not be written."
    assert "secret" not in str(caught.value)
    assert all("secret" not in message for message in _messages(caplog))


def test_bigquery_failure_does_not_echo_the_runner(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    runner = _Runner([BackboneError("secret")])
    with pytest.raises(AuditUnavailable) as caught:
        BigQueryAuditLog(BackboneConfig(), runner).record(_flagship_records())
    assert str(caught.value) == "The audit table could not be written."
    assert "secret" not in str(caught.value)
    assert all("secret" not in message for message in _messages(caplog))


def test_audit_table_stays_on_the_store_events_project() -> None:
    with pytest.raises(BackboneError):
        BigQueryAuditLog(BackboneConfig(project="other-project"), _Runner([]))
    sql = trace_sql(BackboneConfig())
    assert "retailtwin-ai-511002.retailtwin.agent_action_audit" in sql


def test_schema_matches_the_query_columns() -> None:
    schema = json.loads(
        (REPO_ROOT / "infrastructure" / "gcp" / "schemas" / "agent-action-audit.json").read_text(encoding="utf-8")
    )
    names = [column["name"] for column in schema]
    assert list(TRACE_COLUMNS) + ["ingested_at"] == names


def test_audit_source_does_not_score_or_call_a_model() -> None:
    source = Path(records_from_decision.__code__.co_filename).read_text(encoding="utf-8").lower()
    for banned in (
        "openai",
        "gemini",
        "vertex",
        "demo_runtime",
        "kpi.evaluator",
        "services.simulation",
        "chain_of_thought",
        "guardedexecutor",
    ):
        assert banned not in source, banned


def _stored(record: AuditRecord) -> dict[str, object]:
    payload = record.model_dump(mode="json")
    payload["stage"] = record.stage.value
    payload["recorded_at"] = format_occurred_at(record.recorded_at)
    return payload


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "retailtwin_api.audit.trail"
    ]
