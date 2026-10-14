"""Persist one correlated agent-action trace.

Each stage is its own row in ``retailtwin.agent_action_audit``. The day-0
``agent_actions`` table stays the thin ``agent.*`` event landing. This module
does not store a prompt or a chain of thought, and it does not write the Live
Twin.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import NoReturn, Protocol

from pydantic import BaseModel, ConfigDict

from retailtwin_api.backbone import BackboneConfig, BackboneError, format_occurred_at
from retailtwin_api.backbone_gcp import (
    CommandRunner,
    parameter_flag,
    parse_query_output,
    query_command,
)
from retailtwin_api.contracts import Decision
from retailtwin_api.guard.decision_context_guard.hashing import canonical_action

log = logging.getLogger(__name__)

AUDIT_TABLE = "agent_action_audit"
MAX_REASON = 280
MAX_CODE = 80
MAX_TOKEN = 200

TRACE_COLUMNS = (
    "record_id",
    "correlation_id",
    "decision_id",
    "action_id",
    "store_id",
    "sku",
    "stage",
    "trigger_ref",
    "evidence_refs",
    "reason_summary",
    "tool_params",
    "simulation_id",
    "predicted_impact",
    "guard_verdict",
    "guard_reason",
    "execution_status",
    "observed_status",
    "recorded_at",
)


class AuditRejected(ValueError):
    """The trace is missing a required fact or carries text that is not a summary."""


class AuditConflict(Exception):
    """This record id is already stored with a different payload."""


class AuditUnavailable(Exception):
    """The audit table could not be read or written."""


class AuditStage(str, Enum):
    """Order of one autonomous run. Later stages are absent when the run stopped."""

    TRIGGER = "trigger"
    EVIDENCE = "evidence"
    DECISION = "decision"
    GUARD = "guard"
    EXECUTION = "execution"
    OBSERVED = "observed"


STAGE_RANK = {stage: index for index, stage in enumerate(AuditStage)}


class AuditOutcome(str, Enum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"


class AuditRecord(BaseModel):
    """One append-only stage. Empty strings mean that fact does not apply."""

    model_config = ConfigDict(frozen=True)

    record_id: str
    correlation_id: str
    decision_id: str
    action_id: str
    store_id: str
    sku: str
    stage: AuditStage
    trigger_ref: str
    evidence_refs: str
    reason_summary: str
    tool_params: str
    simulation_id: str
    predicted_impact: str
    guard_verdict: str
    guard_reason: str
    execution_status: str
    observed_status: str
    recorded_at: datetime


class AuditStore(Protocol):
    def get_trace(self, correlation_id: str) -> list[AuditRecord]: ...

    def insert(self, record: AuditRecord) -> None: ...


def records_from_decision(
    decision: Decision,
    *,
    trigger: str,
    recorded_at: datetime,
    guard_verdict: str,
    guard_reason: str,
    execution: Sequence[tuple[str, str, str | None]] | None = None,
    observed_status: str | None = None,
    observed_reason: str | None = None,
) -> list[AuditRecord]:
    """Build the stage rows for one decision. The decision object is not modified.

    ``execution`` is ``(action_id, status, error)`` in proposed-action order.
    ``action_id`` must be ``{decision_id}:{index}``. ``predicted_impact`` is the
    decision's own ``kpi_score`` rendered as JSON. ``-1.0`` stays the unscored
    sentinel. This function does not compute a KPI.
    """

    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise AuditRejected("recorded_at must be timezone-aware.")
    trigger_ref = _token(trigger, "trigger")
    if not decision.evidence:
        raise AuditRejected("The decision carries no evidence.")
    correlations = {_token(bundle.correlation_id, "correlation_id") for bundle in decision.evidence}
    stores = {_token(bundle.store_id, "store_id") for bundle in decision.evidence}
    if len(correlations) != 1:
        raise AuditRejected("Evidence must carry one correlation id.")
    if len(stores) != 1:
        raise AuditRejected("Evidence must carry one store id.")
    correlation_id = next(iter(correlations))
    store_id = next(iter(stores))
    decision_id = _token(decision.decision_id, "decision_id")
    refs = _evidence_refs(decision)
    reason = _summary(decision.expected_impact.description, required=True)
    impact = _impact(decision.expected_impact.kpi_score)
    actions_json = json.dumps(
        [canonical_action(action) for action in decision.proposed_actions],
        sort_keys=True,
        separators=(",", ":"),
    )
    skus = [action.sku for action in decision.proposed_actions]
    sku = skus[0] if skus and all(item == skus[0] for item in skus) else ""
    if sku:
        sku = _token(sku, "sku")
    simulation_id = _token(decision.simulation_id, "simulation_id", required=False)
    verdict = _code(guard_verdict, "guard_verdict")
    guard_code = _code(guard_reason, "guard_reason")
    if observed_status and not execution:
        raise AuditRejected("An observed result requires an execution result.")

    def row(stage: AuditStage, record_id: str, **updates: str) -> AuditRecord:
        payload = {
            "record_id": record_id,
            "correlation_id": correlation_id,
            "decision_id": decision_id,
            "action_id": "",
            "store_id": store_id,
            "sku": sku,
            "stage": stage,
            "trigger_ref": trigger_ref,
            "evidence_refs": "",
            "reason_summary": "",
            "tool_params": "",
            "simulation_id": "",
            "predicted_impact": "",
            "guard_verdict": "",
            "guard_reason": "",
            "execution_status": "",
            "observed_status": "",
            "recorded_at": recorded_at,
        }
        payload.update(updates)
        return AuditRecord.model_validate(payload)

    records = [
        row(AuditStage.TRIGGER, f"{correlation_id}:trigger", decision_id=""),
        row(
            AuditStage.EVIDENCE,
            f"{correlation_id}:evidence:{decision_id}",
            evidence_refs=json.dumps(refs, separators=(",", ":")),
        ),
        row(
            AuditStage.DECISION,
            f"{correlation_id}:decision:{decision_id}",
            reason_summary=reason,
            tool_params=actions_json,
            simulation_id=simulation_id,
            predicted_impact=impact,
        ),
        row(
            AuditStage.GUARD,
            f"{correlation_id}:guard:{decision_id}",
            guard_verdict=verdict,
            guard_reason=guard_code,
        ),
    ]
    if execution:
        if len(execution) != len(decision.proposed_actions):
            raise AuditRejected("Execution results must cover every proposed action.")
        for index, item in enumerate(execution):
            action_id, status, error = item
            expected = f"{decision_id}:{index}"
            if action_id != expected:
                raise AuditRejected("Execution action id does not match the decision.")
            action = decision.proposed_actions[index]
            records.append(
                row(
                    AuditStage.EXECUTION,
                    f"{correlation_id}:execution:{action_id}",
                    action_id=action_id,
                    sku=_token(action.sku, "sku"),
                    tool_params=json.dumps(canonical_action(action), sort_keys=True, separators=(",", ":")),
                    execution_status=_code(status, "execution_status"),
                    reason_summary=_summary(error, required=False),
                )
            )
    if observed_status:
        records.append(
            row(
                AuditStage.OBSERVED,
                f"{correlation_id}:observed:{decision_id}",
                observed_status=_code(observed_status, "observed_status"),
                reason_summary=_summary(observed_reason, required=False),
            )
        )
    return records


def record_trace(store: AuditStore, records: Sequence[AuditRecord]) -> AuditOutcome:
    """Insert the missing rows of one trace. A different payload for the same id is refused."""

    batch = _validate_batch(records)
    correlation_id = batch[0].correlation_id
    existing = {item.record_id: item for item in store.get_trace(correlation_id)}
    pending: list[AuditRecord] = []
    for record in batch:
        prior = existing.get(record.record_id)
        if prior is None:
            pending.append(record)
            continue
        if _canonical(prior) != _canonical(record):
            log.info(
                "audit conflict correlation_id=%s record_id=%s",
                correlation_id,
                record.record_id,
            )
            raise AuditConflict("The audit record already exists with a different payload.")
    if not pending:
        log.info("audit recorded correlation_id=%s outcome=duplicate rows=0", correlation_id)
        return AuditOutcome.DUPLICATE
    for record in pending:
        store.insert(record)
    log.info(
        "audit recorded correlation_id=%s outcome=inserted rows=%s",
        correlation_id,
        len(pending),
    )
    return AuditOutcome.INSERTED


def trace(store: AuditStore, correlation_id: str) -> list[AuditRecord]:
    """Return one run in stage order."""

    key = _token(correlation_id, "correlation_id")
    rows = store.get_trace(key)
    return sorted(rows, key=lambda row: (STAGE_RANK[row.stage], row.action_id, row.record_id))


def trace_sql(config: BackboneConfig) -> str:
    """The operator query. ``@correlation_id`` selects one run."""

    table = qualified_audit_table(config)
    columns = ", ".join(
        f"FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', recorded_at) AS recorded_at"
        if name == "recorded_at"
        else name
        for name in TRACE_COLUMNS
    )
    order = (
        "CASE stage "
        "WHEN 'trigger' THEN 1 WHEN 'evidence' THEN 2 WHEN 'decision' THEN 3 "
        "WHEN 'guard' THEN 4 WHEN 'execution' THEN 5 WHEN 'observed' THEN 6 ELSE 7 END, "
        "action_id, record_id"
    )
    return f"SELECT {columns} FROM {table} WHERE correlation_id = @correlation_id ORDER BY {order}"


def qualified_audit_table(config: BackboneConfig) -> str:
    checked = config.validated()
    return f"`{checked.project}.{checked.dataset}.{AUDIT_TABLE}`"


class InMemoryAuditLog:
    """Process stand-in for ``agent_action_audit``. Rows are not a Live Twin."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: dict[str, AuditRecord] = {}

    def get_trace(self, correlation_id: str) -> list[AuditRecord]:
        with self._lock:
            return [row.model_copy(deep=True) for row in self._rows.values() if row.correlation_id == correlation_id]

    def insert(self, record: AuditRecord) -> None:
        with self._lock:
            prior = self._rows.get(record.record_id)
            if prior is not None and _canonical(prior) != _canonical(record):
                raise AuditConflict("The audit record already exists with a different payload.")
            if prior is None:
                self._rows[record.record_id] = record.model_copy(deep=True)

    def record(self, records: Sequence[AuditRecord]) -> AuditOutcome:
        with self._lock:
            return record_trace(self, records)


class BigQueryAuditLog:
    """Query-job writer for ``retailtwin.agent_action_audit``. No streaming insert."""

    def __init__(self, config: BackboneConfig, runner: CommandRunner) -> None:
        self._config = config.validated()
        self._runner = runner

    def get_trace(self, correlation_id: str) -> list[AuditRecord]:
        try:
            stdout = self._runner.run(
                query_command(
                    self._config,
                    trace_sql(self._config),
                    [("correlation_id", "STRING", correlation_id)],
                )
            )
            return [_row_to_record(row) for row in parse_query_output(stdout)]
        except (BackboneError, AuditRejected) as exc:
            _unavailable(exc)

    def insert(self, record: AuditRecord) -> None:
        job_id = "audit_" + hashlib.sha256(record.record_id.encode()).hexdigest()[:32]
        command = query_command(self._config, _insert_sql(self._config), _parameters(record), job_id)
        try:
            self._runner.run(command)
        except BackboneError as exc:
            if "Already Exists" not in str(exc):
                _unavailable(exc)
            self._join(job_id)

    def record(self, records: Sequence[AuditRecord]) -> AuditOutcome:
        return record_trace(self, records)

    def _join(self, job_id: str) -> None:
        try:
            self._runner.run(
                [
                    "bq",
                    "--quiet",
                    f"--project_id={self._config.project}",
                    f"--location={self._config.location}",
                    "wait",
                    "--nofail_on_error",
                    job_id,
                ]
            )
            raw = self._runner.run(
                [
                    "bq",
                    "--quiet",
                    f"--project_id={self._config.project}",
                    f"--location={self._config.location}",
                    "show",
                    "--job=true",
                    "--format=prettyjson",
                    job_id,
                ]
            )
            payload = json.loads(raw)
        except (BackboneError, json.JSONDecodeError) as exc:
            _unavailable(exc)
        status = payload.get("status") if isinstance(payload, dict) else None
        if not isinstance(status, dict) or status.get("state") != "DONE" or status.get("errorResult"):
            log.info("audit job failed job_id=%s", job_id)
            raise AuditUnavailable("The audit table could not be written.")


def _validate_batch(records: Sequence[AuditRecord]) -> list[AuditRecord]:
    batch = list(records)
    if not batch:
        raise AuditRejected("The audit batch is empty.")
    seen: set[str] = set()
    correlation_id = _token(batch[0].correlation_id, "correlation_id")
    for record in batch:
        if record.correlation_id != correlation_id:
            raise AuditRejected("A batch must share one correlation id.")
        if record.recorded_at.tzinfo is None or record.recorded_at.utcoffset() is None:
            raise AuditRejected("recorded_at must be timezone-aware.")
        _token(record.record_id, "record_id", limit=600)
        _summary(record.reason_summary, required=False)
        for label, value in (
            ("decision_id", record.decision_id),
            ("action_id", record.action_id),
            ("store_id", record.store_id),
            ("sku", record.sku),
            ("trigger_ref", record.trigger_ref),
            ("evidence_refs", record.evidence_refs),
            ("tool_params", record.tool_params),
            ("simulation_id", record.simulation_id),
            ("predicted_impact", record.predicted_impact),
            ("guard_verdict", record.guard_verdict),
            ("guard_reason", record.guard_reason),
            ("execution_status", record.execution_status),
            ("observed_status", record.observed_status),
        ):
            _plain(value, label)
        if record.record_id in seen:
            raise AuditRejected("A batch repeats a record id.")
        seen.add(record.record_id)
        if not record.store_id.strip():
            raise AuditRejected("store_id is blank.")
    return batch


def _evidence_refs(decision: Decision) -> list[str]:
    refs: list[str] = []
    for bundle in decision.evidence:
        bundle_id = _token(bundle.bundle_id, "bundle_id")
        if not bundle.entity_versions:
            raise AuditRejected("Evidence has no entity version.")
        for sku, version in bundle.entity_versions.items():
            refs.append(f"{bundle_id}:{_token(str(sku), 'sku')}={_token(str(version), 'entity_version')}")
    return sorted(refs)


def _impact(score: object) -> str:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise AuditRejected("predicted impact is not a number.")
    return json.dumps(score)


def _summary(value: str | None, *, required: bool) -> str:
    text = "" if value is None else value.strip()
    _plain(text, "reason_summary")
    if len(text) > MAX_REASON:
        raise AuditRejected("Audit text is longer than a reason summary.")
    if required and not text:
        raise AuditRejected("A reason summary is required.")
    return text


def _code(value: str, label: str) -> str:
    text = value.strip()
    _plain(text, label)
    if not text or len(text) > MAX_CODE:
        raise AuditRejected(f"{label} is not a reason code.")
    return text


def _token(value: str | None, label: str, *, required: bool = True, limit: int = MAX_TOKEN) -> str:
    text = "" if value is None else value.strip()
    _plain(text, label)
    if required and not text:
        raise AuditRejected(f"{label} is blank.")
    if len(text) > limit:
        raise AuditRejected(f"{label} is too long.")
    return text


def _plain(value: str, label: str) -> None:
    if "\n" in value or "\r" in value:
        raise AuditRejected(f"{label} cannot contain a newline.")


def _canonical(record: AuditRecord) -> str:
    payload = record.model_dump(mode="json")
    payload["recorded_at"] = format_occurred_at(record.recorded_at)
    payload["stage"] = record.stage.value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _insert_sql(config: BackboneConfig) -> str:
    table = qualified_audit_table(config)
    names = ", ".join((*TRACE_COLUMNS, "ingested_at"))
    values = ", ".join(f"@{name}" if name != "recorded_at" else "@recorded_at" for name in TRACE_COLUMNS)
    return (
        f"INSERT INTO {table} ({names}) "
        f"SELECT {values}, CURRENT_TIMESTAMP() "
        "FROM (SELECT 1) "
        f"WHERE NOT EXISTS (SELECT 1 FROM {table} WHERE record_id = @record_id)"
    )


def _parameters(record: AuditRecord) -> list[tuple[str, str, str]]:
    payload = record.model_dump(mode="json")
    parameters: list[tuple[str, str, str]] = []
    for name in TRACE_COLUMNS:
        if name == "recorded_at":
            parameters.append((name, "TIMESTAMP", format_occurred_at(record.recorded_at)))
            continue
        value = payload[name]
        if name == "stage":
            value = record.stage.value
        parameters.append((name, "STRING", str(value)))
    for name, _type_name, value in parameters:
        parameter_flag(name, "STRING", value)
    return parameters


def _row_to_record(row: Mapping[str, object]) -> AuditRecord:
    try:
        stage = AuditStage(str(row["stage"]))
        recorded = row["recorded_at"]
        if not isinstance(recorded, str):
            raise AuditUnavailable("The audit query returned no timestamp.")
        text = recorded.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        recorded_at = datetime.fromisoformat(text)
        if recorded_at.tzinfo is None:
            raise AuditUnavailable("The audit query returned a naive timestamp.")
        payload: dict[str, object] = {"stage": stage, "recorded_at": recorded_at}
        for name in TRACE_COLUMNS:
            if name in ("stage", "recorded_at"):
                continue
            value = row.get(name)
            if value is None:
                payload[name] = ""
            elif isinstance(value, str):
                payload[name] = value
            else:
                raise AuditUnavailable("The audit query returned an unexpected column.")
        return AuditRecord.model_validate(payload)
    except (KeyError, ValueError) as exc:
        raise AuditUnavailable("The audit query returned an unexpected row.") from exc


def _unavailable(exc: Exception) -> NoReturn:
    log.info("audit query failed error_type=%s", type(exc).__name__)
    raise AuditUnavailable("The audit table could not be written.") from None
