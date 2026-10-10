import base64
import json
import threading
import time

import pytest

from retailtwin_api.backbone import (
    DEFAULT_FIXTURE,
    BackboneError,
    InsertJobFailed,
    MemoryLedger,
    MemoryPipe,
    MemoryQuarantine,
    MemorySink,
    PulledMessage,
    canonical_body,
    config_from_env,
    deliver,
    format_attributes,
    handle_message,
    insert_job_id,
    land,
    load_fixture,
    message_attributes,
    parse_event,
    row_to_event,
    run_trace,
)
from retailtwin_api.backbone_gcp import (
    BigQuerySink,
    FirestoreRest,
    GcloudPipe,
    HttpResponse,
    command_env,
    parse_pull_output,
)
from retailtwin_api.schemas import StoreEvent
from retailtwin_api.settings import REPO_ROOT


class FakeRunner:
    def __init__(self, output: str = "") -> None:
        self.commands: list[list[str]] = []
        self.output = output
        self._lock = threading.Lock()

    def run(self, args: list[str]) -> str:
        with self._lock:
            self.commands.append(args)
            return self.output


class CountingSink(MemorySink):
    def __init__(self) -> None:
        super().__init__()
        self.inserts = 0
        self._insert_lock = threading.Lock()

    def insert(self, table: str, event: StoreEvent, job_id: str = "") -> None:
        with self._insert_lock:
            self.inserts += 1
        super().insert(table, event, job_id)


def event() -> StoreEvent:
    return load_fixture(DEFAULT_FIXTURE)


def test_fixture_keeps_the_correlation_id() -> None:
    sale = event()

    assert sale.event_id == "evt-sale-0001"
    assert sale.correlation_id == "run-20261007-001"
    assert sale.event_type == "sale.completed"
    assert sale.store_id == "store-001"
    assert sale.sku == "P001"
    assert sale.quantity == 3


def test_canonical_body_is_stable_for_the_same_instant() -> None:
    sale = event()
    payload = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    payload["occurred_at"] = "2026-10-07T08:01:00+00:00"
    shifted = StoreEvent.model_validate(payload)

    assert canonical_body(sale) == canonical_body(shifted)
    assert "run-20261007-001" in canonical_body(sale)
    assert parse_event(canonical_body(sale)) == sale


def test_schema_requires_the_correlation_id() -> None:
    schema = json.loads((REPO_ROOT / "data" / "schemas" / "store-event.schema.json").read_text())

    assert schema["additionalProperties"] is False
    assert "correlation_id" in schema["required"]
    assert "event_id" in schema["required"]
    assert schema["properties"]["quantity"]["minimum"] == 1


def test_same_event_id_lands_once_and_a_replay_is_a_duplicate() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()

    first = land(sink, sale, ledger)
    replay = land(sink, sale, ledger)

    assert first.outcome == "inserted"
    assert replay.outcome == "duplicate"
    assert replay.event is not None
    assert replay.event.correlation_id == "run-20261007-001"
    assert sink.count("sales_events", sale.event_id) == 1
    held = ledger.held(sale.event_id)
    assert held is not None
    assert held[0] == "sales_events"
    assert held[1] == sale


def test_a_different_payload_does_not_replace_the_stored_event() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()
    land(sink, sale, ledger)

    conflict = land(sink, sale.model_copy(update={"quantity": 9}), ledger)

    assert conflict.outcome == "conflict"
    assert conflict.event is not None
    assert conflict.event.quantity == 3
    assert conflict.event.correlation_id == "run-20261007-001"
    assert sink.count("sales_events", sale.event_id) == 1
    held = ledger.held(sale.event_id)
    assert held is not None
    assert held[1].quantity == 3


def test_the_same_event_id_cannot_also_land_as_inventory() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()
    land(sink, sale, ledger)

    conflict = land(sink, sale.model_copy(update={"event_type": "inventory.adjusted"}), ledger)

    assert conflict.outcome == "conflict"
    assert sink.count("inventory_events", sale.event_id) == 0
    assert sink.count("sales_events", sale.event_id) == 1


def test_inventory_and_agent_events_use_their_own_tables() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()

    inventory = land(
        sink,
        sale.model_copy(update={"event_id": "evt-inv-0001", "event_type": "inventory.adjusted"}),
        ledger,
    )
    action = land(
        sink,
        sale.model_copy(update={"event_id": "evt-agent-0001", "event_type": "agent.action"}),
        ledger,
    )

    assert inventory.table == "inventory_events"
    assert action.table == "agent_actions"


def test_an_unknown_event_type_is_rejected() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()

    rejected = land(sink, sale.model_copy(update={"event_type": "promotion.started"}), ledger)

    assert rejected.outcome == "rejected"
    assert sink.count("sales_events", sale.event_id) == 0
    assert ledger.held(sale.event_id) is None


def test_an_attribute_that_disagrees_with_the_body_is_not_stored() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()
    attributes = message_attributes(sale)
    attributes["correlation_id"] = "run-other"

    rejected = handle_message(sink, canonical_body(sale), attributes, ledger)

    assert rejected.outcome == "rejected"
    assert rejected.reason == "attribute_mismatch"
    assert sink.count("sales_events", sale.event_id) == 0
    assert ledger.held(sale.event_id) is None


def test_missing_and_extra_attributes_are_rejected() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()
    full = message_attributes(sale)
    missing_event = dict(full)
    del missing_event["event_id"]
    missing_correlation = dict(full)
    del missing_correlation["correlation_id"]
    cases = [
        ({}, "missing_attribute"),
        (missing_event, "missing_attribute"),
        (missing_correlation, "missing_attribute"),
        ({**full, "authorization": "allow"}, "unexpected_attribute"),
    ]

    for attributes, reason in cases:
        rejected = handle_message(sink, canonical_body(sale), attributes, ledger)
        assert rejected.outcome == "rejected"
        assert rejected.reason == reason

    assert sink.count("sales_events", sale.event_id) == 0
    assert ledger.held(sale.event_id) is None


def test_trace_preserves_the_correlation_id_and_detects_the_replay() -> None:
    report = run_trace(event(), MemoryPipe(), MemorySink(), timeout_s=1)

    assert report == {
        "event_id": "evt-sale-0001",
        "correlation_id": "run-20261007-001",
        "table": "sales_events",
        "first": "inserted",
        "replay": "duplicate",
        "rows": 1,
    }


def test_trace_conflict_leaves_the_original_row() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()
    changed = sale.model_copy(update={"quantity": 9})
    land(sink, changed, ledger)

    with pytest.raises(BackboneError, match="First delivery was conflict"):
        run_trace(sale, MemoryPipe(), sink, ledger=ledger, timeout_s=1)

    assert sink.get("sales_events", sale.event_id).quantity == 9
    assert sink.count("sales_events", sale.event_id) == 1
    held = ledger.held(sale.event_id)
    assert held is not None
    assert held[1].quantity == 9


def test_a_duplicate_claim_repairs_a_missing_row() -> None:
    sale = event()
    ledger = MemoryLedger()
    ledger.claim(sale, "sales_events")
    sink = MemorySink()

    landing = land(sink, sale, ledger)

    assert landing.outcome == "duplicate"
    assert sink.count("sales_events", sale.event_id) == 1


def test_a_conflict_does_not_write_the_derived_row() -> None:
    sale = event()
    ledger = MemoryLedger()
    ledger.claim(sale, "sales_events")
    sink = MemorySink()

    conflict = land(sink, sale.model_copy(update={"quantity": 9}), ledger)

    assert conflict.outcome == "conflict"
    assert sink.count("sales_events", sale.event_id) == 0


def test_a_new_claim_keeps_an_existing_matching_row() -> None:
    sale = event()
    sink = MemorySink()
    sink.insert("sales_events", sale)

    landing = land(sink, sale, MemoryLedger())

    assert landing.outcome == "duplicate"
    assert sink.count("sales_events", sale.event_id) == 1


def test_concurrent_claims_have_one_owner_and_one_row() -> None:
    sale = event()
    sink = CountingSink()
    ledger = MemoryLedger()
    barrier = threading.Barrier(8)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        landing = land(sink, sale, ledger)
        with lock:
            outcomes.append(landing.outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(outcomes) == 8
    assert set(outcomes) <= {"inserted", "duplicate"}
    assert outcomes.count("inserted") <= 1
    assert sink.inserts == 1
    assert sink.count("sales_events", sale.event_id) == 1
    held = ledger.held(sale.event_id)
    assert held is not None
    assert held[1] == sale


def test_concurrent_cross_table_claims_keep_one_owner() -> None:
    sale = event()
    inventory = sale.model_copy(update={"event_type": "inventory.adjusted"})
    sink = CountingSink()
    ledger = MemoryLedger()
    barrier = threading.Barrier(8)
    outcomes: list[tuple[str, str | None]] = []
    lock = threading.Lock()

    def worker(item: StoreEvent) -> None:
        barrier.wait()
        landing = land(sink, item, ledger)
        with lock:
            outcomes.append((landing.outcome, landing.table))

    threads = [threading.Thread(target=worker, args=(sale,)) for _ in range(4)]
    threads.extend(threading.Thread(target=worker, args=(inventory,)) for _ in range(4))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(outcomes) == 8
    assert sink.inserts == 1
    assert sink.count("sales_events", sale.event_id) + sink.count("inventory_events", sale.event_id) == 1
    held = ledger.held(sale.event_id)
    assert held is not None
    owner_table = held[0]
    assert all(table == owner_table for outcome, table in outcomes if outcome in ("inserted", "duplicate"))
    assert any(outcome == "conflict" for outcome, _table in outcomes)


def test_accepted_outcomes_are_acked_and_not_quarantined() -> None:
    sale = event()
    sink = MemorySink()
    ledger = MemoryLedger()
    quarantine = MemoryQuarantine()
    pipe = MemoryPipe()
    attributes = message_attributes(sale)
    messages = [
        PulledMessage("a1", canonical_body(sale), attributes, ""),
        PulledMessage("a2", canonical_body(sale), attributes, ""),
        PulledMessage("a3", canonical_body(sale.model_copy(update={"quantity": 9})), dict(attributes), ""),
    ]

    outcomes = [deliver(pipe, sink, ledger, quarantine, message).outcome for message in messages]

    assert outcomes == ["inserted", "duplicate", "conflict"]
    assert pipe.acked == ["a1", "a2", "a3"]
    assert quarantine.records == []
    assert sink.get("sales_events", sale.event_id).quantity == 3


def test_a_rejected_message_is_quarantined_before_it_is_acked() -> None:
    pipe = MemoryPipe()

    class OrderingQuarantine:
        def __init__(self) -> None:
            self.reasons: list[str] = []

        def record(self, message: PulledMessage, reason: str) -> None:
            assert pipe.acked == []
            self.reasons.append(reason)

    quarantine = OrderingQuarantine()
    message = PulledMessage("bad", "not-json", {}, "")

    landing = deliver(pipe, MemorySink(), MemoryLedger(), quarantine, message)

    assert landing.outcome == "rejected"
    assert landing.reason == "invalid_event"
    assert quarantine.reasons == ["invalid_event"]
    assert pipe.acked == ["bad"]


def test_quarantine_failure_does_not_ack() -> None:
    class FailingQuarantine:
        def record(self, message: PulledMessage, reason: str) -> None:
            raise BackboneError("quarantine unavailable")

    pipe = MemoryPipe()
    message = PulledMessage("bad", "{", {}, "")

    with pytest.raises(BackboneError, match="quarantine unavailable"):
        deliver(pipe, MemorySink(), MemoryLedger(), FailingQuarantine(), message)

    assert pipe.acked == []


def test_publisher_refuses_an_attribute_unsafe_correlation_id() -> None:
    with pytest.raises(BackboneError, match="correlation_id"):
        message_attributes(event().model_copy(update={"correlation_id": "run,other"}))


def test_formatted_timestamp_matches_the_fixture_instant() -> None:
    sale = event()
    row = {
        "event_id": sale.event_id,
        "correlation_id": sale.correlation_id,
        "event_type": sale.event_type,
        "store_id": sale.store_id,
        "sku": sale.sku,
        "quantity": "3",
        "occurred_at": "2026-10-07T08:01:00.000000Z",
        "source": sale.source,
    }

    assert row_to_event(row) == sale


def test_publish_command_copies_the_correlation_id() -> None:
    sale = event()
    runner = FakeRunner("messageIds: []\n")

    GcloudPipe(config_from_env({}), runner).publish(sale)

    command = runner.commands[0]
    assert command[4] == "store-events"
    assert f"--ordering-key={sale.event_id}" in command
    assert "--attribute=correlation_id=run-20261007-001,event_id=evt-sale-0001,event_type=sale.completed,store_id=store-001" in command
    message = next(part for part in command if part.startswith("--message="))
    assert message == f"--message={canonical_body(sale)}"
    assert format_attributes(message_attributes(sale)) in command[-2]


def test_event_id_stays_a_query_parameter() -> None:
    sale = event().model_copy(update={"event_id": "evt' OR 1=1"})
    runner = FakeRunner("[]")
    sink = BigQuerySink(config_from_env({}), runner)

    assert sink.get("sales_events", sale.event_id) is None

    command = runner.commands[0]
    sql = command[-1]
    assert sale.event_id not in sql
    assert "WHERE event_id = @event_id" in sql
    assert f"--parameter=event_id:STRING:{sale.event_id}" in command


def test_unknown_table_is_rejected_before_a_query() -> None:
    runner = FakeRunner("[]")

    with pytest.raises(BackboneError, match="Unknown table"):
        BigQuerySink(config_from_env({}), runner).get("other_events", "evt-sale-0001")

    assert runner.commands == []


def test_insert_uses_the_sales_table_and_keeps_the_correlation_parameter() -> None:
    sale = event()
    runner = FakeRunner("")

    job_id = insert_job_id(sale.event_id, 1)
    BigQuerySink(config_from_env({}), runner).insert("sales_events", sale, job_id)

    command = runner.commands[0]
    sql = command[-1]
    assert "INSERT INTO `retailtwin-ai-511002.retailtwin.sales_events`" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "--parameter=correlation_id:STRING:run-20261007-001" in command
    assert f"--job_id={job_id}" in command
    assert command.index(f"--job_id={job_id}") < command.index("query")
    assert "streaming" not in sql.lower()


def test_pull_output_decodes_the_event_and_its_correlation_id() -> None:
    sale = event()
    payload = [
        {
            "ackId": "ack-1",
            "message": {
                "data": base64.b64encode(canonical_body(sale).encode()).decode(),
                "attributes": message_attributes(sale),
                "publishTime": "2026-10-08T00:00:00Z",
            },
        }
    ]

    messages = parse_pull_output(json.dumps(payload))

    assert len(messages) == 1
    assert messages[0].ack_id == "ack-1"
    assert messages[0].attributes["correlation_id"] == "run-20261007-001"
    assert parse_event(messages[0].body) == sale


def test_pubsub_uses_the_regional_endpoint() -> None:
    assert command_env()["CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB"] == "https://us-central1-pubsub.googleapis.com/"


def test_config_refuses_another_project() -> None:
    with pytest.raises(BackboneError, match="retailtwin-ai-511002"):
        config_from_env({"GCP_PROJECT_ID": "cn-prj-17cd4"})

    with pytest.raises(BackboneError, match="retailtwin-ai-511002"):
        config_from_env({"GCP_PROJECT_ID": "ess-prj"})

    with pytest.raises(BackboneError, match="us-central1"):
        config_from_env({"GCP_REGION": "us-east1"})


class FakeFirestore:
    """Enforces exists=false under a lock, the same way a commit precondition does."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.docs: dict[str, dict[str, object]] = {}
        self.times: dict[str, str] = {}
        self.rejects: list[dict[str, object]] = []
        self.calls: list[tuple[str, str]] = []
        self._clock = 0

    def _tick(self) -> str:
        self._clock += 1
        return f"t{self._clock}"

    def request(
        self,
        method: str,
        url: str,
        payload: bytes | None,
        headers: dict[str, str],
    ) -> HttpResponse:
        assert headers["Authorization"] == "Bearer test-token"
        assert "Bearer" not in (payload.decode("utf-8") if payload else "")
        body = json.loads(payload) if payload else None
        with self._lock:
            self.calls.append((method, url))
            if method == "POST" and url.endswith(":commit"):
                write = body["writes"][0]
                precondition = write.get("currentDocument") or {}
                name = write["update"]["name"]
                assert "/databases/(default)/documents/store_event_claims/" in name
                if precondition.get("exists") is False:
                    if name in self.docs:
                        return HttpResponse(
                            409,
                            json.dumps({"error": {"code": 409, "status": "ALREADY_EXISTS", "message": "exists"}}),
                        )
                    self.docs[name] = write["update"]["fields"]
                    stamp = self._tick()
                    self.times[name] = stamp
                    return HttpResponse(200, json.dumps({"writeResults": [{"updateTime": stamp}]}))
                stamp = precondition.get("updateTime")
                if isinstance(stamp, str):
                    if self.times.get(name) != stamp:
                        return HttpResponse(
                            400,
                            json.dumps({"error": {"code": 400, "status": "FAILED_PRECONDITION", "message": "stale"}}),
                        )
                    fields = self.docs[name]
                    incoming = write["update"]["fields"]
                    mask = (write.get("updateMask") or {}).get("fieldPaths") or []
                    for path in mask:
                        fields[path] = incoming[path]
                    new_stamp = self._tick()
                    self.times[name] = new_stamp
                    return HttpResponse(200, json.dumps({"writeResults": [{"updateTime": new_stamp}]}))
                return HttpResponse(400, json.dumps({"error": {"status": "INVALID_ARGUMENT", "message": "precondition"}}))
            if method == "GET" and "/documents/store_event_claims/" in url:
                event_id = url.rsplit("/", 1)[-1]
                for name, fields in self.docs.items():
                    if name.endswith("/" + event_id):
                        return HttpResponse(
                            200,
                            json.dumps({"name": name, "fields": fields, "updateTime": self.times[name]}),
                        )
                return HttpResponse(404, json.dumps({"error": {"status": "NOT_FOUND", "message": "missing"}}))
            if method == "POST" and url.endswith("/documents/store_event_rejects"):
                self.rejects.append(body["fields"])
                return HttpResponse(
                    200,
                    json.dumps(
                        {
                            "name": (
                                "projects/retailtwin-ai-511002/databases/(default)"
                                "/documents/store_event_rejects/auto"
                            )
                        }
                    ),
                )
        return HttpResponse(500, json.dumps({"error": {"status": "INTERNAL", "message": "unhandled"}}))


def _firestore(transport: FakeFirestore | None = None, output: str = "test-token\n") -> tuple[FirestoreRest, FakeFirestore]:
    store = transport or FakeFirestore()
    client = FirestoreRest(config_from_env({}), FakeRunner(output), store)
    return client, store


def test_the_default_firestore_transport_accepts_a_request() -> None:
    client = FirestoreRest(config_from_env({}), FakeRunner("test-token\n"))

    assert callable(client.transport.request)


def test_firestore_claim_is_atomic_for_one_event_id() -> None:
    sale = event()
    client, store = _firestore()
    barrier = threading.Barrier(8)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        claim = client.claim(sale, "sales_events")
        with lock:
            outcomes.append(claim.outcome)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("inserted") == 1
    assert outcomes.count("duplicate") == 7
    assert len(store.docs) == 1
    stored = next(iter(store.docs.values()))
    assert stored["canonical"]["stringValue"] == canonical_body(sale)
    assert stored["table"]["stringValue"] == "sales_events"
    assert any(method == "GET" for method, _url in store.calls)


def test_firestore_cross_table_race_keeps_one_document() -> None:
    sale = event()
    inventory = sale.model_copy(update={"event_type": "inventory.adjusted"})
    client, store = _firestore()
    barrier = threading.Barrier(8)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(item: StoreEvent, table: str) -> None:
        barrier.wait()
        claim = client.claim(item, table)
        with lock:
            outcomes.append(claim.outcome)

    threads = [threading.Thread(target=worker, args=(sale, "sales_events")) for _ in range(4)]
    threads.extend(threading.Thread(target=worker, args=(inventory, "inventory_events")) for _ in range(4))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("inserted") == 1
    assert len(store.docs) == 1
    assert set(outcomes) <= {"inserted", "duplicate", "conflict"}
    assert "conflict" in outcomes


def test_firestore_conflict_does_not_replace_the_claim() -> None:
    sale = event()
    client, store = _firestore()

    first = client.claim(sale, "sales_events")
    conflict = client.claim(sale.model_copy(update={"quantity": 9}), "sales_events")
    replay = client.claim(sale, "sales_events")

    assert first.outcome == "inserted"
    assert conflict.outcome == "conflict"
    assert conflict.event.quantity == 3
    assert replay.outcome == "duplicate"
    stored = next(iter(store.docs.values()))
    assert stored["canonical"]["stringValue"] == canonical_body(sale)


def test_firestore_invalid_argument_is_not_a_duplicate() -> None:
    class Invalid:
        def request(self, method: str, url: str, payload: bytes | None, headers: dict[str, str]) -> HttpResponse:
            return HttpResponse(400, json.dumps({"error": {"status": "INVALID_ARGUMENT", "message": "bad"}}))

    client = FirestoreRest(config_from_env({}), FakeRunner("test-token\n"), Invalid())

    with pytest.raises(BackboneError, match="HTTP 400"):
        client.claim(event(), "sales_events")


def test_firestore_precondition_status_reads_the_existing_claim() -> None:
    sale = event()
    fields = {
        "table": {"stringValue": "sales_events"},
        "canonical": {"stringValue": canonical_body(sale)},
    }

    class Precondition:
        def __init__(self) -> None:
            self.gets = 0

        def request(self, method: str, url: str, payload: bytes | None, headers: dict[str, str]) -> HttpResponse:
            if method == "POST":
                return HttpResponse(
                    400,
                    json.dumps({"error": {"status": "FAILED_PRECONDITION", "message": "exists"}}),
                )
            self.gets += 1
            return HttpResponse(200, json.dumps({"fields": fields, "updateTime": "t1"}))

    transport = Precondition()
    client = FirestoreRest(config_from_env({}), FakeRunner("test-token\n"), transport)

    claim = client.claim(sale, "sales_events")

    assert claim.outcome == "duplicate"
    assert transport.gets == 1


def test_firestore_quarantine_keeps_the_reason_and_a_failure_raises() -> None:
    sale = event()
    client, store = _firestore()
    message = PulledMessage("ack", canonical_body(sale), message_attributes(sale), "")

    client.record(message, "invalid_event")

    assert store.rejects[0]["reason"]["stringValue"] == "invalid_event"
    assert "authorization" not in store.rejects[0]["body"]["stringValue"]
    assert store.rejects[0]["truncated"]["booleanValue"] is False

    class Down:
        def request(self, method: str, url: str, payload: bytes | None, headers: dict[str, str]) -> HttpResponse:
            return HttpResponse(503, json.dumps({"error": {"status": "UNAVAILABLE", "message": "down"}}))

    failing = FirestoreRest(config_from_env({}), FakeRunner("test-token\n"), Down())
    with pytest.raises(BackboneError, match="HTTP 503"):
        failing.record(message, "invalid_event")


def test_a_duplicate_without_the_lease_does_not_insert() -> None:
    sale = event()
    ledger = MemoryLedger()
    ledger.claim(sale, "sales_events")
    fence = ledger.acquire_landing(sale.event_id)
    sink = CountingSink()

    with pytest.raises(BackboneError, match="landing lease"):
        land(sink, sale, ledger, wait_s=0)

    assert fence is not None
    assert sink.inserts == 0


def test_two_landers_issue_one_bigquery_insert_for_a_missing_row() -> None:
    sale = event()
    client, _store = _firestore()
    assert client.claim(sale, "sales_events").outcome == "inserted"
    runner = _GatedInsert(sale)
    sink = BigQuerySink(config_from_env({}), runner)
    outcomes: list[str] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            landing = land(sink, sale, client, wait_s=2)
        except BackboneError as exc:
            with lock:
                errors.append(str(exc))
            return
        with lock:
            outcomes.append(landing.outcome)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert runner.started.wait(timeout=2)
        time.sleep(0.1)
        assert runner.inserts == 1
    finally:
        runner.allow.set()
        for thread in threads:
            thread.join(timeout=2)

    assert errors == []
    assert runner.inserts == 1
    assert sorted(outcomes) == ["duplicate", "duplicate"]
    assert not any(thread.is_alive() for thread in threads)


def test_an_existing_job_id_is_joined_instead_of_inserted_again() -> None:
    sale = event()
    job_id = insert_job_id(sale.event_id, 1)
    runner = _ScriptedRunner(
        [
            BackboneError(f"Already Exists: Job retailtwin-ai-511002:us-central1.{job_id}"),
            "",
            json.dumps({"status": {"state": "DONE"}}),
        ]
    )

    BigQuerySink(config_from_env({}), runner).insert("sales_events", sale, job_id)

    assert sum("query" in command for command in runner.commands) == 1
    assert f"--job_id={job_id}" in runner.commands[0]
    assert runner.commands[1][-1] == job_id
    assert "wait" in runner.commands[1]
    assert "show" in runner.commands[2]


def test_a_finished_error_job_does_not_count_as_a_second_insert() -> None:
    sale = event()
    job_id = insert_job_id(sale.event_id, 1)
    runner = _ScriptedRunner(
        [
            BackboneError(f"Already Exists: Job retailtwin-ai-511002:us-central1.{job_id}"),
            "",
            json.dumps({"status": {"state": "DONE", "errorResult": {"reason": "invalidQuery"}}}),
        ]
    )

    with pytest.raises(InsertJobFailed):
        BigQuerySink(config_from_env({}), runner).insert("sales_events", sale, job_id)

    assert sum("query" in command for command in runner.commands) == 1


def test_a_failed_insert_job_uses_the_next_generation() -> None:
    sale = event()
    ledger = MemoryLedger()
    sink = _FailOnceSink()

    landing = land(sink, sale, ledger)

    assert landing.outcome == "inserted"
    assert sink.jobs == [insert_job_id(sale.event_id, 1), insert_job_id(sale.event_id, 2)]
    assert sink.count("sales_events", sale.event_id) == 1


def test_an_expired_lease_joins_the_same_insert_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("retailtwin_api.backbone.LANDING_LEASE_S", 0.0)
    sale = event()
    ledger = MemoryLedger()
    ledger.claim(sale, "sales_events")
    sink = _SharedJobSink()
    outcomes: list[str] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            landing = land(sink, sale, ledger, wait_s=2)
        except BackboneError as exc:
            with lock:
                errors.append(str(exc))
            return
        with lock:
            outcomes.append(landing.outcome)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert sink.started.wait(timeout=2)
        time.sleep(0.1)
        assert sink.executions == 1
        assert set(sink.calls) == {insert_job_id(sale.event_id, 1)}
    finally:
        sink.allow.set()
        for thread in threads:
            thread.join(timeout=2)

    assert errors == []
    assert sink.executions == 1
    assert sink.count("sales_events", sale.event_id) == 1
    assert sorted(outcomes) == ["duplicate", "duplicate"]
    assert not any(thread.is_alive() for thread in threads)


def test_acquire_keeps_one_insert_generation_across_a_takeover() -> None:
    sale = event()
    client, store = _firestore()
    assert client.claim(sale, "sales_events").outcome == "inserted"

    lease = client.acquire_landing(sale.event_id)

    assert lease is not None
    assert lease.generation == 1
    stored = next(iter(store.docs.values()))
    assert stored["insert_generation"]["integerValue"] == "1"
    nxt = client.fail_insert(sale.event_id, lease.fence, lease.generation)
    assert nxt is not None
    assert nxt.generation == 2
    assert client.fail_insert(sale.event_id, lease.fence, lease.generation) is None
    assert stored["insert_generation"]["integerValue"] == "2"


class _ScriptedRunner:
    def __init__(self, steps: list[object]) -> None:
        self.steps = list(steps)
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> str:
        self.commands.append(args)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return str(step)


class _FailOnceSink(MemorySink):
    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[str] = []

    def insert(self, table: str, event: StoreEvent, job_id: str = "") -> None:
        self.jobs.append(job_id)
        if len(self.jobs) == 1:
            raise InsertJobFailed(job_id)
        super().insert(table, event, job_id)


class _SharedJobSink(MemorySink):
    """One BigQuery job id runs one insert. A second caller waits for that job."""

    def __init__(self) -> None:
        super().__init__()
        self.executions = 0
        self.calls: list[str] = []
        self.started = threading.Event()
        self.allow = threading.Event()
        self._jobs: dict[str, str] = {}
        self._cv = threading.Condition()

    def insert(self, table: str, event: StoreEvent, job_id: str = "") -> None:
        with self._cv:
            self.calls.append(job_id)
            state = self._jobs.get(job_id)
            if state == "done":
                return
            if state == "running":
                while self._jobs.get(job_id) == "running":
                    self._cv.wait(timeout=2)
                if self._jobs.get(job_id) != "done":
                    raise BackboneError("insert was not released")
                return
            self._jobs[job_id] = "running"
            self.executions += 1
            self.started.set()
        if not self.allow.wait(timeout=2):
            raise BackboneError("insert was not released")
        super().insert(table, event, job_id)
        with self._cv:
            self._jobs[job_id] = "done"
            self._cv.notify_all()


class _GatedInsert:
    """Holds the BigQuery insert open so a second lander can race it."""

    def __init__(self, sale: StoreEvent) -> None:
        self.sale = sale
        self.inserts = 0
        self.started = threading.Event()
        self.allow = threading.Event()
        self._lock = threading.Lock()
        self._wrote = False

    def run(self, args: list[str]) -> str:
        sql = args[-1]
        if "INSERT INTO" in sql:
            with self._lock:
                self.inserts += 1
            self.started.set()
            if not self.allow.wait(timeout=2):
                raise BackboneError("insert was not released")
            with self._lock:
                self._wrote = True
            return ""
        if "sales_events" in sql and "SELECT" in sql:
            with self._lock:
                wrote = self._wrote
            if not wrote:
                return "[]"
            sale = self.sale
            return json.dumps(
                [
                    {
                        "event_id": sale.event_id,
                        "correlation_id": sale.correlation_id,
                        "event_type": sale.event_type,
                        "store_id": sale.store_id,
                        "sku": sale.sku,
                        "quantity": str(sale.quantity),
                        "occurred_at": "2026-10-07T08:01:00.000000Z",
                        "source": sale.source,
                    }
                ]
            )
        return "[]"
