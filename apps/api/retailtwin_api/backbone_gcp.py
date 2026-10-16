"""Pub/Sub, Firestore claim, and BigQuery adapters.

The claim document is the event-id owner. BigQuery landing uses query DML,
not streaming inserts.
"""

import base64
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, cast
from urllib.parse import quote

from retailtwin_api.backbone import (
    LANDING_LEASE_S,
    TABLES,
    BackboneConfig,
    BackboneError,
    Claim,
    InsertJobFailed,
    LandingLease,
    PulledMessage,
    canonical_body,
    claim_id_ok,
    format_attributes,
    format_occurred_at,
    message_attributes,
    parse_event,
    require_sale,
    row_to_event,
)
from retailtwin_api.schemas import StoreEvent

_QUERY_BYTE_CAP = "100000000"


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> str: ...


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    # Ordering keys are rejected on the global endpoint when the topic stores
    # messages only in us-central1. Publish and pull through that region.
    env["CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB"] = "https://us-central1-pubsub.googleapis.com/"
    return env


class SubprocessRunner:
    def run(self, args: list[str]) -> str:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            env=command_env(),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise BackboneError(detail or f"Command failed with exit {completed.returncode}.")
        return completed.stdout


def qualified_table(config: BackboneConfig, table: str) -> str:
    config.validated()
    if table not in TABLES:
        raise BackboneError(f"Unknown table {table}.")
    return f"`{config.project}.{config.dataset}.{table}`"


def parameter_flag(name: str, type_name: str, value: str) -> str:
    if any(char in value for char in "\n\r"):
        raise BackboneError(f"{name} contains a newline.")
    return f"--parameter={name}:{type_name}:{value}"


def event_parameters(event: StoreEvent) -> list[tuple[str, str, str]]:
    return [
        ("event_id", "STRING", event.event_id),
        ("correlation_id", "STRING", event.correlation_id),
        ("event_type", "STRING", event.event_type),
        ("store_id", "STRING", event.store_id),
        ("sku", "STRING", event.sku),
        ("quantity", "INT64", str(event.quantity)),
        ("occurred_at", "TIMESTAMP", format_occurred_at(event.occurred_at)),
        ("source", "STRING", event.source),
    ]


def _job_id_ok(job_id: str) -> bool:
    if not job_id or len(job_id) > 1024:
        return False
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    return all(char in allowed for char in job_id)


def query_command(
    config: BackboneConfig,
    sql: str,
    parameters: list[tuple[str, str, str]],
    job_id: str | None = None,
) -> list[str]:
    command = [
        "bq",
        "--quiet",
        f"--project_id={config.project}",
        f"--location={config.location}",
    ]
    if job_id is not None:
        command.append(f"--job_id={job_id}")
    command.extend(
        [
            "query",
            "--nouse_legacy_sql",
            "--format=prettyjson",
            f"--maximum_bytes_billed={_QUERY_BYTE_CAP}",
        ]
    )
    for name, type_name, value in parameters:
        command.append(parameter_flag(name, type_name, value))
    command.append(sql)
    return command


def parse_query_output(stdout: str) -> list[dict[str, object]]:
    text = stdout.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BackboneError("BigQuery did not return JSON.") from exc
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    raise BackboneError("BigQuery returned an unexpected payload.")


def parse_pull_output(stdout: str) -> list[PulledMessage]:
    text = stdout.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BackboneError("Pub/Sub pull did not return JSON.") from exc
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise BackboneError("Pub/Sub pull returned an unexpected payload.")
    messages: list[PulledMessage] = []
    for item in payload:
        if not isinstance(item, dict):
            raise BackboneError("Pub/Sub pull returned an unexpected message.")
        ack_id = item.get("ackId") or item.get("ack_id")
        raw_message = item.get("message") or {}
        if not isinstance(ack_id, str) or not ack_id:
            raise BackboneError("Pub/Sub pull is missing an ack id.")
        if not isinstance(raw_message, dict):
            raise BackboneError("Pub/Sub pull returned an unexpected message.")
        attributes = raw_message.get("attributes") or {}
        if not isinstance(attributes, dict):
            attributes = {}
        messages.append(
            PulledMessage(
                ack_id=ack_id,
                body=_decode_body(raw_message.get("data") or ""),
                attributes={str(key): str(value) for key, value in attributes.items()},
                publish_time=str(raw_message.get("publishTime") or raw_message.get("publish_time") or ""),
            )
        )
    return messages


class GcloudPipe:
    def __init__(self, config: BackboneConfig, runner: CommandRunner) -> None:
        self.config = config.validated()
        self.runner = runner

    def publish(self, event: StoreEvent) -> None:
        require_sale(event)
        self.runner.run(
            [
                "gcloud",
                "pubsub",
                "topics",
                "publish",
                self.config.topic,
                "--project",
                self.config.project,
                "--quiet",
                f"--message={canonical_body(event)}",
                f"--attribute={format_attributes(message_attributes(event))}",
                f"--ordering-key={event.event_id}",
            ]
        )

    def pull(self, limit: int = 10) -> list[PulledMessage]:
        bounded = min(10, max(1, limit))
        stdout = self.runner.run(
            [
                "gcloud",
                "pubsub",
                "subscriptions",
                "pull",
                self.config.subscription,
                "--project",
                self.config.project,
                "--quiet",
                "--no-auto-ack",
                f"--limit={bounded}",
                "--format=json",
            ]
        )
        return parse_pull_output(stdout)

    def ack(self, ack_id: str) -> None:
        if not ack_id or any(char in ack_id for char in "\n\r"):
            raise BackboneError("Refusing an empty ack id.")
        self.runner.run(
            [
                "gcloud",
                "pubsub",
                "subscriptions",
                "ack",
                self.config.subscription,
                "--project",
                self.config.project,
                "--quiet",
                f"--ack-ids={ack_id}",
            ]
        )


class BigQuerySink:
    def __init__(self, config: BackboneConfig, runner: CommandRunner) -> None:
        self.config = config.validated()
        self.runner = runner

    def get(self, table: str, event_id: str) -> StoreEvent | None:
        sql = (
            "SELECT event_id, correlation_id, event_type, store_id, sku, quantity, "
            "FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', occurred_at) AS occurred_at, source "
            f"FROM {qualified_table(self.config, table)} "
            "WHERE event_id = @event_id"
        )
        rows = self._rows(sql, [("event_id", "STRING", event_id)])
        if not rows:
            return None
        if len(rows) > 1:
            raise BackboneError(f"event_id {event_id} has {len(rows)} rows in {table}.")
        return row_to_event(rows[0])

    def count(self, table: str, event_id: str) -> int:
        sql = (
            "SELECT COUNT(*) AS row_count "
            f"FROM {qualified_table(self.config, table)} "
            "WHERE event_id = @event_id"
        )
        rows = self._rows(sql, [("event_id", "STRING", event_id)])
        if len(rows) != 1:
            raise BackboneError(f"Could not count {event_id} in {table}.")
        row_count: object = rows[0]["row_count"]
        return int(cast(str, row_count))

    def insert(self, table: str, event: StoreEvent, job_id: str) -> None:
        if not _job_id_ok(job_id):
            raise BackboneError("Insert job id is not a BigQuery job id.")
        target = qualified_table(self.config, table)
        sql = (
            "INSERT INTO "
            f"{target} "
            "(event_id, correlation_id, event_type, store_id, sku, quantity, occurred_at, source, ingested_at) "
            "SELECT @event_id, @correlation_id, @event_type, @store_id, @sku, @quantity, "
            "@occurred_at, @source, CURRENT_TIMESTAMP() "
            "FROM (SELECT 1) "
            f"WHERE NOT EXISTS (SELECT 1 FROM {target} WHERE event_id = @event_id)"
        )
        try:
            self.runner.run(query_command(self.config, sql, event_parameters(event), job_id))
        except BackboneError as exc:
            if "Already Exists" not in str(exc):
                raise
            self._join_existing_job(job_id)

    def _join_existing_job(self, job_id: str) -> None:
        self.runner.run(
            [
                "bq",
                "--quiet",
                f"--project_id={self.config.project}",
                f"--location={self.config.location}",
                "wait",
                "--nofail_on_error",
                job_id,
            ]
        )
        raw = self.runner.run(
            [
                "bq",
                "--quiet",
                f"--project_id={self.config.project}",
                f"--location={self.config.location}",
                "show",
                "--job=true",
                "--format=prettyjson",
                job_id,
            ]
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackboneError("BigQuery job status was not JSON.") from exc
        status = payload.get("status") if isinstance(payload, dict) else None
        if not isinstance(status, dict) or status.get("state") != "DONE":
            raise BackboneError("Insert job is still running.")
        if status.get("errorResult"):
            raise InsertJobFailed(job_id)

    def _rows(self, sql: str, parameters: list[tuple[str, str, str]]) -> list[dict[str, object]]:
        stdout = self.runner.run(query_command(self.config, sql, parameters))
        return parse_query_output(stdout)


def _decode_body(raw: object) -> str:
    if not isinstance(raw, str) or raw == "":
        return ""
    try:
        return base64.b64decode(raw).decode("utf-8")
    except (ValueError, UnicodeError):
        return ""


_CLAIM_COLLECTION = "store_event_claims"
_REJECT_COLLECTION = "store_event_rejects"
_BODY_CAP = 100_000
_REASON_CAP = 500


class HttpResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse: ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        request = urllib.request.Request(url, data=payload, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return HttpResponse(response.status, response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read().decode("utf-8", errors="replace"))
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            if "Bearer" in reason:
                reason = "request failed"
            raise BackboneError(f"Firestore request failed. {reason}") from exc


def _database_root(project: str) -> str:
    return f"https://firestore.googleapis.com/v1/projects/{project}/databases/%28default%29"


def _claim_name(project: str, event_id: str) -> str:
    return f"projects/{project}/databases/(default)/documents/{_CLAIM_COLLECTION}/{event_id}"


def _http_error(action: str, status: int, body: str) -> BackboneError:
    message = ""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            message = error["message"]
    if not message:
        message = body.strip()
    detail = f"{action} failed with HTTP {status}."
    if message:
        detail = f"{detail} {message[:300]}"
    return BackboneError(detail)


def _precondition_failed(status: int, body: str) -> bool:
    if status == 409:
        return True
    if status != 400:
        return False
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return False
    return error.get("status") in {"FAILED_PRECONDITION", "ALREADY_EXISTS"}


def _string_field(fields: dict[str, object], name: str) -> str:
    text = _optional_string(fields, name)
    if text is None:
        raise BackboneError(f"Claim is missing {name}.")
    return text


def _optional_string(fields: dict[str, object], name: str) -> str | None:
    value = fields.get(name)
    if not isinstance(value, dict):
        return None
    text = value.get("stringValue")
    if not isinstance(text, str):
        return None
    return text


def _timestamp_field(fields: dict[str, object], name: str) -> datetime | None:
    value = fields.get(name)
    if not isinstance(value, dict):
        return None
    text = value.get("timestampValue")
    if not isinstance(text, str) or not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackboneError(f"Claim has an unreadable {name}.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _generation_field(fields: dict[str, object]) -> int:
    value = fields.get("insert_generation")
    if value is None:
        return 1
    if not isinstance(value, dict):
        raise BackboneError("Claim has an unreadable insert generation.")
    raw = value.get("integerValue")
    if isinstance(raw, str) and raw.isdigit() and int(raw) >= 1:
        return int(raw)
    raise BackboneError("Claim has an unreadable insert generation.")


def _lease_held(deadline: datetime | None) -> bool:
    # A landing claim with no readable deadline stays held. Do not steal it.
    if deadline is None:
        return True
    return deadline > datetime.now(timezone.utc)


def _commit_update_time(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BackboneError("Landing lease commit was not JSON.") from exc
    results = payload.get("writeResults") if isinstance(payload, dict) else None
    if isinstance(results, list) and results and isinstance(results[0], dict):
        stamp = results[0].get("updateTime")
        if isinstance(stamp, str) and stamp:
            return stamp
    raise BackboneError("Landing lease commit did not return an update time.")


@dataclass(frozen=True)
class _ClaimSnapshot:
    update_time: str
    table: str
    canonical: str
    state: str
    deadline: datetime | None
    generation: int


class FirestoreRest:
    """Compare-and-create claim and reject quarantine over the Firestore REST API.

    Identity uses currentDocument.exists=false. The derived-row write uses a
    separate compare-and-update from claimed to landing. One lander holds that
    lease. No Google client library.
    """

    def __init__(
        self,
        config: BackboneConfig,
        runner: CommandRunner,
        transport: HttpTransport | None = None,
    ) -> None:
        self.config = config.validated()
        self.runner = runner
        self.transport = transport or UrllibTransport()
        self._token: str | None = None
        self._token_lock = threading.Lock()

    def claim(self, event: StoreEvent, table: str) -> Claim:
        if table not in TABLES:
            raise BackboneError(f"Unknown table {table}.")
        if not claim_id_ok(event.event_id):
            raise BackboneError("event_id cannot be used as a claim document.")
        payload = {
            "writes": [
                {
                    "update": {
                        "name": _claim_name(self.config.project, event.event_id),
                        "fields": {
                            "event_id": {"stringValue": event.event_id},
                            "table": {"stringValue": table},
                            "canonical": {"stringValue": canonical_body(event)},
                            "state": {"stringValue": "claimed"},
                            "claimed_at": {
                                "timestampValue": format_occurred_at(datetime.now(timezone.utc))
                            },
                        },
                    },
                    "currentDocument": {"exists": False},
                }
            ]
        }
        response = self._call("POST", f"{_database_root(self.config.project)}/documents:commit", cast(dict[str, object], payload))
        if response.status == 200:
            return Claim("inserted", table, event.model_copy(deep=True))
        if _precondition_failed(response.status, response.body):
            return self._classify_existing(event, table)
        raise _http_error("Claiming the event id", response.status, response.body)

    def acquire_landing(self, event_id: str) -> LandingLease | None:
        snapshot = self._read_snapshot(event_id)
        if snapshot.state == "landed":
            return None
        if snapshot.state == "landing" and _lease_held(snapshot.deadline):
            return None
        if snapshot.state not in {"claimed", "landing"}:
            raise BackboneError(f"Claim for {event_id} has an unknown state.")
        deadline = datetime.now(timezone.utc) + timedelta(seconds=LANDING_LEASE_S)
        generation = snapshot.generation
        payload = {
            "writes": [
                {
                    "update": {
                        "name": _claim_name(self.config.project, event_id),
                        "fields": {
                            "state": {"stringValue": "landing"},
                            "landing_deadline": {"timestampValue": format_occurred_at(deadline)},
                            "insert_generation": {"integerValue": str(generation)},
                        },
                    },
                    "updateMask": {"fieldPaths": ["state", "landing_deadline", "insert_generation"]},
                    "currentDocument": {"updateTime": snapshot.update_time},
                }
            ]
        }
        response = self._call("POST", f"{_database_root(self.config.project)}/documents:commit", cast(dict[str, object], payload))
        if response.status == 200:
            return LandingLease(_commit_update_time(response.body), generation)
        if _precondition_failed(response.status, response.body):
            return None
        raise _http_error("Acquiring the landing lease", response.status, response.body)

    def fail_insert(self, event_id: str, fence: object, generation: int) -> LandingLease | None:
        if not isinstance(fence, str) or not fence or generation < 1:
            return None
        deadline = datetime.now(timezone.utc) + timedelta(seconds=LANDING_LEASE_S)
        nxt = generation + 1
        payload = {
            "writes": [
                {
                    "update": {
                        "name": _claim_name(self.config.project, event_id),
                        "fields": {
                            "insert_generation": {"integerValue": str(nxt)},
                            "landing_deadline": {"timestampValue": format_occurred_at(deadline)},
                        },
                    },
                    "updateMask": {"fieldPaths": ["insert_generation", "landing_deadline"]},
                    "currentDocument": {"updateTime": fence},
                }
            ]
        }
        response = self._call("POST", f"{_database_root(self.config.project)}/documents:commit", cast(dict[str, object], payload))
        if response.status == 200:
            return LandingLease(_commit_update_time(response.body), nxt)
        if _precondition_failed(response.status, response.body):
            return None
        raise _http_error("Advancing the insert generation", response.status, response.body)

    def mark_landed(self, event_id: str, fence: object) -> None:
        self._transition(event_id, fence, "landed", "Marking the claim landed")

    def release_landing(self, event_id: str, fence: object) -> None:
        self._transition(event_id, fence, "claimed", "Releasing the landing lease", optional=True)

    def record(self, message: PulledMessage, reason: str) -> None:
        body = message.body
        truncated = len(body) > _BODY_CAP
        if truncated:
            body = body[:_BODY_CAP]
        reason_text = (reason or "rejected").strip() or "rejected"
        if len(reason_text) > _REASON_CAP:
            reason_text = reason_text[:_REASON_CAP]
        payload = {
            "fields": {
                "reason": {"stringValue": reason_text},
                "body": {"stringValue": body},
                "attributes": {
                    "stringValue": json.dumps(dict(message.attributes), sort_keys=True, separators=(",", ":"))
                },
                "received_at": {"timestampValue": format_occurred_at(datetime.now(timezone.utc))},
                "truncated": {"booleanValue": truncated},
            }
        }
        url = f"{_database_root(self.config.project)}/documents/{_REJECT_COLLECTION}"
        response = self._call("POST", url, cast(dict[str, object], payload))
        if response.status not in (200, 201):
            raise _http_error("Quarantine", response.status, response.body)

    def _classify_existing(self, event: StoreEvent, table: str) -> Claim:
        snapshot = self._read_snapshot(event.event_id)
        try:
            stored = parse_event(snapshot.canonical)
        except BackboneError as exc:
            raise BackboneError(f"Claim for {event.event_id} is unreadable.") from exc
        if snapshot.table == table and stored == event:
            return Claim("duplicate", snapshot.table, stored)
        return Claim("conflict", snapshot.table, stored)

    def _transition(
        self,
        event_id: str,
        fence: object,
        state: str,
        action: str,
        optional: bool = False,
    ) -> None:
        if not isinstance(fence, str) or not fence:
            raise BackboneError("Lost the landing lease.")
        payload = {
            "writes": [
                {
                    "update": {
                        "name": _claim_name(self.config.project, event_id),
                        "fields": {"state": {"stringValue": state}},
                    },
                    "updateMask": {"fieldPaths": ["state"]},
                    "currentDocument": {"updateTime": fence},
                }
            ]
        }
        response = self._call("POST", f"{_database_root(self.config.project)}/documents:commit", cast(dict[str, object], payload))
        if response.status == 200:
            return
        if optional and _precondition_failed(response.status, response.body):
            return
        raise _http_error(action, response.status, response.body)

    def _read_snapshot(self, event_id: str) -> _ClaimSnapshot:
        url = (
            f"{_database_root(self.config.project)}/documents/{_CLAIM_COLLECTION}/"
            f"{quote(event_id, safe='')}"
        )
        response = self._call("GET", url, None)
        if response.status != 200:
            raise _http_error("Reading the event claim", response.status, response.body)
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise BackboneError("Event claim was not JSON.") from exc
        if not isinstance(payload, dict):
            raise BackboneError("Event claim was not JSON.")
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            raise BackboneError("Event claim has no fields.")
        update_time = payload.get("updateTime")
        if not isinstance(update_time, str) or not update_time:
            raise BackboneError("Event claim is missing an update time.")
        state = _optional_string(fields, "state") or "claimed"
        if state not in {"claimed", "landing", "landed"}:
            raise BackboneError(f"Claim for {event_id} has an unknown state.")
        return _ClaimSnapshot(
            update_time=update_time,
            table=_string_field(fields, "table"),
            canonical=_string_field(fields, "canonical"),
            state=state,
            deadline=_timestamp_field(fields, "landing_deadline"),
            generation=_generation_field(fields),
        )

    def _call(self, method: str, url: str, payload: Mapping[str, object] | None) -> HttpResponse:
        raw = None if payload is None else json.dumps(payload).encode("utf-8")
        try:
            return self.transport.request(method, url, raw, self._headers())
        except (BackboneError, AssertionError):
            raise
        except Exception as exc:
            raise BackboneError("Firestore request failed.") from exc

    def _headers(self) -> dict[str, str]:
        with self._token_lock:
            if self._token is None:
                raw = self.runner.run(["gcloud", "auth", "print-access-token", "--quiet"])
                token = raw.strip()
                if not token or any(char in token for char in "\n\r\t "):
                    raise BackboneError("Could not read an access token.")
                self._token = token
            token = self._token
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# GcpPubSubEventPipe — google-cloud-pubsub backed EventPipe (ADR 0023)
# ---------------------------------------------------------------------------


class _PubSubPublishFuture(Protocol):
    """Subset of the publisher Future surface the pipe actually uses."""

    def result(self, timeout: float | None = None) -> str: ...


class _PubSubPublisherClient(Protocol):
    """Subset of ``google.cloud.pubsub_v1.PublisherClient`` the pipe uses."""

    def publish(
        self,
        topic: str,
        data: bytes,
        **kwargs: str,
    ) -> _PubSubPublishFuture: ...


class _PubSubReceivedMessage(Protocol):
    """Subset of ``google.pubsub_v1.types.ReceivedMessage`` the pipe uses."""

    ack_id: str
    message: object


class _PubSubPullResponse(Protocol):
    received_messages: list[_PubSubReceivedMessage]


class _PubSubMessageView(Protocol):
    data: bytes
    attributes: Mapping[str, str]
    publish_time: object


class _PubSubSubscriberClient(Protocol):
    """Subset of ``google.cloud.pubsub_v1.SubscriberClient`` the pipe uses."""

    def pull(
        self,
        request: Mapping[str, object],
        timeout: float | None = ...,
    ) -> _PubSubPullResponse: ...

    def acknowledge(
        self,
        request: Mapping[str, object],
        timeout: float | None = ...,
    ) -> None: ...

    def modify_ack_deadline(
        self,
        request: Mapping[str, object],
        timeout: float | None = ...,
    ) -> None: ...


def _default_subscriber_factory() -> _PubSubSubscriberClient:
    """Import the real subscriber client lazily so tests can mock it."""

    from google.cloud.pubsub_v1 import SubscriberClient

    return cast(_PubSubSubscriberClient, SubscriberClient())


class GcpPubSubEventPipe:
    """EventPipe backed by Google Cloud Pub/Sub via the sync client.

    Boundary: this module owns the wire format (canonical body + attributes
    from :mod:`retailtwin_api.backbone`) and the ack-id lifecycle; the
    observation/decision logic lives in the consumer and the starter.

    The publisher client is built once and cached — it holds an HTTP/2
    connection that is safe to reuse. The subscriber is built per pull call:
    the HTTP push handler is short-lived and a per-call client keeps the
    ack-deadline window tight without background threads.
    """

    def __init__(
        self,
        project: str,
        topic: str,
        subscription: str,
        *,
        publisher: _PubSubPublisherClient | None = None,
        subscriber_factory: Callable[[], _PubSubSubscriberClient] | None = None,
    ) -> None:
        if not project:
            raise BackboneError("GcpPubSubEventPipe requires a project id.")
        if not topic:
            raise BackboneError("GcpPubSubEventPipe requires a topic name.")
        if not subscription:
            raise BackboneError("GcpPubSubEventPipe requires a subscription name.")
        self._project = project
        self._topic_path = f"projects/{project}/topics/{topic}"
        self._subscription_path = f"projects/{project}/subscriptions/{subscription}"
        self._publisher: _PubSubPublisherClient | None = publisher
        self._publisher_lock = threading.Lock()
        self._subscriber_factory: Callable[[], _PubSubSubscriberClient] = (
            subscriber_factory or _default_subscriber_factory
        )

    @property
    def topic_path(self) -> str:
        return self._topic_path

    @property
    def subscription_path(self) -> str:
        return self._subscription_path

    def publish(self, event: StoreEvent) -> None:
        require_sale(event)
        publisher = self._get_publisher()
        body = canonical_body(event).encode("utf-8")
        attributes = message_attributes(event)
        future = publisher.publish(self._topic_path, body, **attributes)
        # The synchronous publisher returns a Future; wait so the caller sees
        # the same back-pressure as the gcloud path.
        future.result(timeout=30.0)

    def pull(self, limit: int = 10) -> list[PulledMessage]:
        bounded = max(1, min(limit, 100))
        subscriber = self._subscriber_factory()
        response = subscriber.pull(
            request={"subscription": self._subscription_path, "max_messages": bounded},
            timeout=10.0,
        )
        messages: list[PulledMessage] = []
        for received in response.received_messages:
            view = self._message_view(received)
            if view is None:
                continue
            messages.append(
                PulledMessage(
                    ack_id=received.ack_id,
                    body=view.data.decode("utf-8", errors="replace"),
                    attributes={str(key): str(value) for key, value in view.attributes.items()},
                    publish_time=str(getattr(view.publish_time, "rfc3339", lambda: "")() or ""),
                )
            )
        return messages

    def ack(self, ack_id: str) -> None:
        if not ack_id or any(char in ack_id for char in "\n\r"):
            raise BackboneError("Refusing an empty ack id.")
        subscriber = self._subscriber_factory()
        subscriber.acknowledge(
            request={"subscription": self._subscription_path, "ack_ids": [ack_id]},
            timeout=10.0,
        )

    def _get_publisher(self) -> _PubSubPublisherClient:
        cached = self._publisher
        if cached is not None:
            return cached
        with self._publisher_lock:
            if self._publisher is None:
                from google.cloud.pubsub_v1 import PublisherClient

                self._publisher = cast(_PubSubPublisherClient, PublisherClient())
            return self._publisher

    def _message_view(self, received: _PubSubReceivedMessage) -> _PubSubMessageView | None:
        message = getattr(received, "message", None)
        if message is None:
            return None
        # The Protocol declares the shape we need; cast keeps mypy quiet
        # without leaking the upstream type into module-level imports.
        return cast(_PubSubMessageView, message)
