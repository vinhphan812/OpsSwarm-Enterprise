"""Normalized store-event identity.

One event_id has one claim. BigQuery rows are derived history.
A replay of the same payload is a duplicate.
"""

import hashlib
import json
import os
import re
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ValidationError

from retailtwin_api.schemas import StoreEvent
from retailtwin_api.settings import REPO_ROOT

ALLOWED_PROJECT = "retailtwin-ai-511002"
ALLOWED_LOCATION = "us-central1"
ALLOWED_TOPIC = "store-events"
ALLOWED_SUBSCRIPTION = "store-events-analytics"
ALLOWED_DATASET = "retailtwin"
TABLES = ("sales_events", "inventory_events", "agent_actions")
SALE_COMPLETED = "sale.completed"
DEFAULT_FIXTURE = REPO_ROOT / "data" / "synthetic" / "sale-completed.json"
REQUIRED_ATTRIBUTES = ("correlation_id", "event_id", "event_type", "store_id")
_ATTRIBUTE_TEXT = re.compile(r"^[A-Za-z0-9_.:@+-]+$")
_CLAIM_ID_LIMIT = 1500
LANDING_LEASE_S = 120.0
_LANDING_WAIT_S = 5.0


class BackboneError(Exception):
    """The store-event backbone cannot publish or land this event."""


class InsertJobFailed(BackboneError):
    """The BigQuery job for this generation finished with an error."""


@dataclass(frozen=True)
class LandingLease:
    fence: object
    generation: int


@dataclass(frozen=True)
class BackboneConfig:
    project: str = ALLOWED_PROJECT
    location: str = ALLOWED_LOCATION
    topic: str = ALLOWED_TOPIC
    subscription: str = ALLOWED_SUBSCRIPTION
    dataset: str = ALLOWED_DATASET

    def validated(self) -> "BackboneConfig":
        if self.project != ALLOWED_PROJECT:
            raise BackboneError(
                f"Refusing project {self.project}. Store events stay on {ALLOWED_PROJECT}."
            )
        if self.location != ALLOWED_LOCATION:
            raise BackboneError(f"Refusing location {self.location}. Store events stay in {ALLOWED_LOCATION}.")
        if self.topic != ALLOWED_TOPIC:
            raise BackboneError(f"Refusing topic {self.topic}.")
        if self.subscription != ALLOWED_SUBSCRIPTION:
            raise BackboneError(f"Refusing subscription {self.subscription}.")
        if self.dataset != ALLOWED_DATASET:
            raise BackboneError(f"Refusing dataset {self.dataset}.")
        return self


def config_from_env(env: Mapping[str, str] | None = None) -> BackboneConfig:
    source = os.environ if env is None else env
    region = source.get("GCP_REGION", "").strip()
    location = source.get("BIGQUERY_LOCATION", "").strip()
    if region and location and region != location:
        raise BackboneError("GCP_REGION and BIGQUERY_LOCATION differ.")
    return BackboneConfig(
        project=source.get("GCP_PROJECT_ID", "").strip() or ALLOWED_PROJECT,
        location=location or region or ALLOWED_LOCATION,
        topic=source.get("STORE_EVENTS_TOPIC", "").strip() or ALLOWED_TOPIC,
        subscription=source.get("STORE_EVENTS_SUBSCRIPTION", "").strip() or ALLOWED_SUBSCRIPTION,
        dataset=source.get("BIGQUERY_DATASET", "").strip() or ALLOWED_DATASET,
    ).validated()


@dataclass(frozen=True)
class Landing:
    outcome: Literal["inserted", "duplicate", "conflict", "rejected"]
    event: StoreEvent | None
    table: str | None
    reason: str | None = None


@dataclass(frozen=True)
class Claim:
    outcome: Literal["inserted", "duplicate", "conflict"]
    table: str
    event: StoreEvent


@dataclass(frozen=True)
class PulledMessage:
    ack_id: str
    body: str
    attributes: dict[str, str]
    publish_time: str


class EventSink(Protocol):
    def get(self, table: str, event_id: str) -> StoreEvent | None: ...

    def insert(self, table: str, event: StoreEvent, job_id: str) -> None: ...

    def count(self, table: str, event_id: str) -> int: ...


class ClaimLedger(Protocol):
    def claim(self, event: StoreEvent, table: str) -> Claim: ...

    def acquire_landing(self, event_id: str) -> LandingLease | None: ...

    def fail_insert(self, event_id: str, fence: object, generation: int) -> LandingLease | None: ...

    def mark_landed(self, event_id: str, fence: object) -> None: ...

    def release_landing(self, event_id: str, fence: object) -> None: ...


class Quarantine(Protocol):
    def record(self, message: PulledMessage, reason: str) -> None: ...


class EventPipe(Protocol):
    def publish(self, event: StoreEvent) -> None: ...

    def pull(self, limit: int = 10) -> list[PulledMessage]: ...

    def ack(self, ack_id: str) -> None: ...


def table_for(event_type: str) -> str | None:
    if event_type == SALE_COMPLETED:
        return "sales_events"
    if event_type.startswith("inventory.") and event_type != "inventory.":
        return "inventory_events"
    if event_type.startswith("agent.") and event_type != "agent.":
        return "agent_actions"
    return None


def format_occurred_at(value: datetime) -> str:
    text = value.astimezone(timezone.utc).isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def canonical_body(event: StoreEvent) -> str:
    payload = {
        "correlation_id": event.correlation_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "occurred_at": format_occurred_at(event.occurred_at),
        "quantity": event.quantity,
        "sku": event.sku,
        "source": event.source,
        "store_id": event.store_id,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def parse_event(body: str) -> StoreEvent:
    try:
        return StoreEvent.model_validate_json(body)
    except (ValidationError, ValueError) as exc:
        raise BackboneError("invalid store event") from exc


def load_fixture(path: Path) -> StoreEvent:
    try:
        return StoreEvent.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise BackboneError(f"Cannot read fixture {path}") from exc


def require_sale(event: StoreEvent) -> None:
    if event.event_type != SALE_COMPLETED:
        raise BackboneError("This publisher emits sale.completed only.")


def insert_job_id(event_id: str, generation: int) -> str:
    """One BigQuery job id for this event id and insert generation.

    A later lander submits this same id. BigQuery then returns the existing
    job instead of starting a second insert. The id is a hash so every allowed
    event id fits the job-id alphabet and the 1024 character limit.
    """

    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise BackboneError("Insert generation must be positive.")
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
    job_id = f"store-event-{digest}-{generation}"
    if len(job_id) > 1024:
        raise BackboneError("Insert job id is not a BigQuery job id.")
    return job_id


def claim_id_ok(event_id: str) -> bool:
    if event_id in {".", ".."}:
        return False
    if len(event_id.encode("utf-8")) > _CLAIM_ID_LIMIT:
        return False
    if event_id.startswith("__") and event_id.endswith("__"):
        return False
    return _ATTRIBUTE_TEXT.fullmatch(event_id) is not None


def message_attributes(event: StoreEvent) -> dict[str, str]:
    attributes = {
        "correlation_id": event.correlation_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "store_id": event.store_id,
    }
    for key, value in attributes.items():
        if _ATTRIBUTE_TEXT.fullmatch(value) is None:
            raise BackboneError(f"{key} cannot be copied into a Pub/Sub attribute.")
    return attributes


def format_attributes(attributes: Mapping[str, str]) -> str:
    return ",".join(f"{key}={attributes[key]}" for key in sorted(attributes))


def attribute_problem(event: StoreEvent, attributes: Mapping[str, str]) -> str | None:
    expected = {
        "correlation_id": event.correlation_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "store_id": event.store_id,
    }
    if any(key not in attributes for key in REQUIRED_ATTRIBUTES):
        return "missing_attribute"
    if any(key not in expected for key in attributes):
        return "unexpected_attribute"
    if any(attributes[key] != value for key, value in expected.items()):
        return "attribute_mismatch"
    return None


def row_to_event(row: Mapping[str, object]) -> StoreEvent:
    return StoreEvent.model_validate(
        {
            "event_id": row["event_id"],
            "correlation_id": row["correlation_id"],
            "event_type": row["event_type"],
            "store_id": row["store_id"],
            "sku": row["sku"],
            "quantity": row["quantity"],
            "occurred_at": row["occurred_at"],
            "source": row["source"],
        }
    )


class MemorySink:
    """In-memory stand-in for the three analytical tables."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, StoreEvent]] = {table: {} for table in TABLES}
        self._lock = threading.Lock()

    def get(self, table: str, event_id: str) -> StoreEvent | None:
        self._known(table)
        with self._lock:
            row = self.rows[table].get(event_id)
            if row is None:
                return None
            return row.model_copy(deep=True)

    def insert(self, table: str, event: StoreEvent, job_id: str = "") -> None:
        self._known(table)
        del job_id
        with self._lock:
            self.rows[table].setdefault(event.event_id, event.model_copy(deep=True))

    def count(self, table: str, event_id: str) -> int:
        self._known(table)
        with self._lock:
            return int(event_id in self.rows[table])

    def _known(self, table: str) -> None:
        if table not in TABLES:
            raise BackboneError(f"Unknown table {table}.")


class _MemoryClaim:
    def __init__(self, table: str, event: StoreEvent) -> None:
        self.table = table
        self.event = event
        self.state = "claimed"
        self.fence = 1
        self.generation = 1
        self.deadline = 0.0


class MemoryLedger:
    """In-process model of the claim document.

    The lock covers one compare-and-swap. It is not a process-wide land lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claims: dict[str, _MemoryClaim] = {}

    def claim(self, event: StoreEvent, table: str) -> Claim:
        if table not in TABLES:
            raise BackboneError(f"Unknown table {table}.")
        if not claim_id_ok(event.event_id):
            raise BackboneError("event_id cannot be used as a claim document.")
        with self._lock:
            existing = self._claims.get(event.event_id)
            if existing is None:
                stored = event.model_copy(deep=True)
                self._claims[event.event_id] = _MemoryClaim(table, stored)
                return Claim("inserted", table, stored.model_copy(deep=True))
            if existing.table == table and existing.event == event:
                return Claim("duplicate", existing.table, existing.event.model_copy(deep=True))
            return Claim("conflict", existing.table, existing.event.model_copy(deep=True))

    def acquire_landing(self, event_id: str) -> LandingLease | None:
        with self._lock:
            record = self._claims.get(event_id)
            if record is None:
                raise BackboneError(f"event_id {event_id} has no claim.")
            now = time.monotonic()
            if record.state == "landed":
                return None
            if record.state == "landing" and record.deadline > now:
                return None
            if record.generation < 1:
                record.generation = 1
            record.state = "landing"
            record.fence += 1
            record.deadline = now + LANDING_LEASE_S
            return LandingLease(record.fence, record.generation)

    def fail_insert(self, event_id: str, fence: object, generation: int) -> LandingLease | None:
        with self._lock:
            record = self._require(event_id)
            if record.state != "landing" or record.fence != fence or record.generation != generation:
                return None
            record.generation += 1
            record.fence += 1
            record.deadline = time.monotonic() + LANDING_LEASE_S
            return LandingLease(record.fence, record.generation)

    def mark_landed(self, event_id: str, fence: object) -> None:
        with self._lock:
            record = self._require(event_id)
            if record.state != "landing" or record.fence != fence:
                raise BackboneError("Lost the landing lease.")
            record.state = "landed"

    def release_landing(self, event_id: str, fence: object) -> None:
        with self._lock:
            record = self._require(event_id)
            if record.state != "landing" or record.fence != fence:
                return
            record.state = "claimed"
            record.deadline = 0.0

    def held(self, event_id: str) -> tuple[str, StoreEvent] | None:
        with self._lock:
            record = self._claims.get(event_id)
            if record is None:
                return None
            return record.table, record.event.model_copy(deep=True)

    def _require(self, event_id: str) -> _MemoryClaim:
        record = self._claims.get(event_id)
        if record is None:
            raise BackboneError(f"event_id {event_id} has no claim.")
        return record


class MemoryQuarantine:
    """Records rejected messages in process memory."""

    def __init__(self) -> None:
        self.records: list[tuple[PulledMessage, str]] = []

    def record(self, message: PulledMessage, reason: str) -> None:
        self.records.append((message, reason))


class MemoryPipe:
    """Queues canonical messages so the trace can run without Google Cloud."""

    def __init__(self) -> None:
        self.pending: list[PulledMessage] = []
        self.acked: list[str] = []
        self._sequence = 0

    def publish(self, event: StoreEvent) -> None:
        require_sale(event)
        self._sequence += 1
        self.pending.append(
            PulledMessage(
                ack_id=str(self._sequence),
                body=canonical_body(event),
                attributes=message_attributes(event),
                publish_time="",
            )
        )

    def pull(self, limit: int = 10) -> list[PulledMessage]:
        batch = self.pending[:limit]
        self.pending = self.pending[limit:]
        return batch

    def ack(self, ack_id: str) -> None:
        self.acked.append(ack_id)


def find_existing(sink: EventSink, event_id: str) -> tuple[str, StoreEvent] | None:
    found: list[tuple[str, StoreEvent]] = []
    for table in TABLES:
        row = sink.get(table, event_id)
        if row is not None:
            found.append((table, row))
    if not found:
        return None
    if len(found) > 1:
        raise BackboneError(f"event_id {event_id} is stored in more than one table.")
    return found[0]


def land(
    sink: EventSink,
    event: StoreEvent,
    ledger: ClaimLedger,
    wait_s: float = _LANDING_WAIT_S,
) -> Landing:
    table = table_for(event.event_type)
    if table is None:
        return Landing("rejected", None, None, "unsupported_event_type")
    if not claim_id_ok(event.event_id):
        return Landing("rejected", event, None, "unsafe_event_id")
    claim = ledger.claim(event, table)
    if claim.outcome == "conflict":
        return Landing("conflict", claim.event, claim.table)
    deadline = time.monotonic() + wait_s
    while True:
        lease = ledger.acquire_landing(event.event_id)
        if lease is not None:
            return _write_derived(sink, event, ledger, table, claim, lease)
        existing = find_existing(sink, event.event_id)
        if existing is not None:
            return _existing_landing(existing, event, table)
        if time.monotonic() >= deadline:
            raise BackboneError("Another lander holds the landing lease.")
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))


def _existing_landing(
    existing: tuple[str, StoreEvent],
    event: StoreEvent,
    table: str,
) -> Landing:
    existing_table, stored = existing
    if existing_table == table and stored == event:
        return Landing("duplicate", stored, table)
    return Landing("conflict", stored, existing_table)


def _write_derived(
    sink: EventSink,
    event: StoreEvent,
    ledger: ClaimLedger,
    table: str,
    claim: Claim,
    lease: LandingLease,
) -> Landing:
    existing = find_existing(sink, event.event_id)
    if existing is not None:
        existing_table, stored = existing
        if existing_table == table and stored == event:
            _mark_or_duplicate(ledger, event.event_id, lease.fence)
            return Landing("duplicate", stored, table)
        ledger.release_landing(event.event_id, lease.fence)
        return Landing("conflict", stored, existing_table)
    current = _insert_generation(sink, event, ledger, table, lease)
    stored_after_insert: StoreEvent | None = sink.get(table, event.event_id)
    if stored_after_insert is None or stored_after_insert != event:
        ledger.release_landing(event.event_id, current.fence)
        if stored_after_insert is None:
            raise BackboneError(f"event_id {event.event_id} was not stored.")
        return Landing("conflict", stored_after_insert, table)
    if not _mark_or_duplicate(ledger, event.event_id, current.fence):
        return Landing("duplicate", stored_after_insert, table)
    if claim.outcome == "inserted":
        return Landing("inserted", stored_after_insert, table)
    return Landing("duplicate", stored_after_insert, table)


def _insert_generation(
    sink: EventSink,
    event: StoreEvent,
    ledger: ClaimLedger,
    table: str,
    lease: LandingLease,
) -> LandingLease:
    current = lease
    retried = False
    while True:
        try:
            sink.insert(table, event, insert_job_id(event.event_id, current.generation))
            return current
        except InsertJobFailed as exc:
            if retried:
                ledger.release_landing(event.event_id, current.fence)
                raise BackboneError(f"Insert job for {event.event_id} failed.") from exc
            nxt = ledger.fail_insert(event.event_id, current.fence, current.generation)
            if nxt is None:
                raise BackboneError("Lost the landing lease.") from exc
            current = nxt
            retried = True
        except Exception:
            ledger.release_landing(event.event_id, current.fence)
            raise


def _mark_or_duplicate(ledger: ClaimLedger, event_id: str, fence: object) -> bool:
    try:
        ledger.mark_landed(event_id, fence)
    except BackboneError as exc:
        if "Lost the landing lease." not in str(exc):
            raise
        return False
    return True


def handle_message(
    sink: EventSink,
    body: str,
    attributes: Mapping[str, str],
    ledger: ClaimLedger,
) -> Landing:
    try:
        event = parse_event(body)
    except BackboneError:
        return Landing("rejected", None, None, "invalid_event")
    problem = attribute_problem(event, attributes)
    if problem is not None:
        return Landing("rejected", event, None, problem)
    return land(sink, event, ledger)


def deliver(
    pipe: EventPipe,
    sink: EventSink,
    ledger: ClaimLedger,
    quarantine: Quarantine,
    message: PulledMessage,
) -> Landing:
    landing = handle_message(sink, message.body, message.attributes, ledger)
    if landing.outcome == "rejected":
        quarantine.record(message, landing.reason or "rejected")
    elif landing.outcome not in ("inserted", "duplicate", "conflict"):
        raise BackboneError(f"Unknown landing outcome {landing.outcome}.")
    pipe.ack(message.ack_id)
    return landing


def consume_matching(
    pipe: EventPipe,
    sink: EventSink,
    event: StoreEvent,
    ledger: ClaimLedger,
    quarantine: Quarantine,
    timeout_s: float,
) -> tuple[PulledMessage, Landing]:
    deadline = time.monotonic() + timeout_s
    announced = False
    while time.monotonic() < deadline:
        batch = pipe.pull()
        if not batch:
            if not announced:
                print(f"waiting for {event.event_id}", file=sys.stderr)
                announced = True
            time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
            continue
        matched: tuple[PulledMessage, Landing] | None = None
        for message in batch:
            landing = deliver(pipe, sink, ledger, quarantine, message)
            if _targets(message, event):
                matched = (message, landing)
        if matched is not None:
            return matched
    raise BackboneError(f"Timed out waiting for {event.event_id}.")


def run_trace(
    event: StoreEvent,
    pipe: EventPipe,
    sink: EventSink,
    ledger: ClaimLedger | None = None,
    quarantine: Quarantine | None = None,
    timeout_s: float = 90.0,
) -> dict[str, object]:
    require_sale(event)
    owner = ledger if ledger is not None else MemoryLedger()
    holding = quarantine if quarantine is not None else MemoryQuarantine()
    pipe.publish(event)
    first_message, first = consume_matching(pipe, sink, event, owner, holding, timeout_s)
    _require_correlation(first_message, event)
    if first.outcome not in ("inserted", "duplicate"):
        raise BackboneError(f"First delivery was {first.outcome}.")
    found = find_existing(sink, event.event_id)
    if found is None or found[0] != "sales_events" or found[1] != event:
        raise BackboneError("Stored sale does not match the published event.")
    if sink.count("sales_events", event.event_id) != 1:
        raise BackboneError("event_id landed more than once.")
    pipe.publish(event)
    replay_message, replay = consume_matching(pipe, sink, event, owner, holding, timeout_s)
    _require_correlation(replay_message, event)
    if replay.outcome != "duplicate":
        raise BackboneError(f"Replay was {replay.outcome}.")
    if sink.count("sales_events", event.event_id) != 1:
        raise BackboneError("Replay added another row.")
    stored_after = find_existing(sink, event.event_id)
    if stored_after is None or stored_after[1] != event:
        raise BackboneError("Replay changed the stored event.")
    held = owner.held(event.event_id) if isinstance(owner, MemoryLedger) else None
    if isinstance(owner, MemoryLedger):
        if held is None or held[0] != "sales_events" or held[1] != event:
            raise BackboneError("Claim does not match the published event.")
    return {
        "event_id": event.event_id,
        "correlation_id": stored_after[1].correlation_id,
        "table": "sales_events",
        "first": first.outcome,
        "replay": "duplicate",
        "rows": 1,
    }


def _targets(message: PulledMessage, event: StoreEvent) -> bool:
    try:
        parsed = parse_event(message.body)
    except BackboneError:
        return False
    return parsed.event_id == event.event_id and parsed.event_type == event.event_type


def _require_correlation(message: PulledMessage, event: StoreEvent) -> None:
    if message.attributes.get("correlation_id") != event.correlation_id:
        raise BackboneError("correlation_id was not preserved on the message.")
    if message.attributes.get("event_id") != event.event_id:
        raise BackboneError("event_id was not preserved on the message.")
