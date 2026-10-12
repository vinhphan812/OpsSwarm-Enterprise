import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from retailtwin_api.backbone import (
    BackboneError,
    MemoryLedger,
    MemoryPipe,
    MemoryQuarantine,
    MemorySink,
    deliver,
)
from retailtwin_api.backbone_gcp import GcloudPipe
from retailtwin_api.demand_surge import (
    CANONICAL_SEED,
    FIXTURE_PATH,
    SKU,
    DemandSurgeNotice,
    detect_demand_surge,
    load_committed_surge,
    load_env_file,
    main,
    publish_demand_surge,
    replay_demand_surge,
    reset_weekend_demand_surge,
    scenario_document,
)
from retailtwin_api.schemas import StoreEvent


class RecordingObserver:
    def __init__(self) -> None:
        self.notices: list[DemandSurgeNotice] = []

    def receive_demand_surge(self, notice: DemandSurgeNotice) -> None:
        self.notices.append(notice)


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str]) -> str:
        self.commands.append(args)
        return ""


def test_reset_rebuilds_the_same_p017_series() -> None:
    first = reset_weekend_demand_surge()
    second = reset_weekend_demand_surge(CANONICAL_SEED)

    assert first == second
    assert [event.event_id for event in first] == [
        "evt-p017-base-0001",
        "evt-p017-base-0002",
        "evt-p017-base-0003",
        "evt-p017-base-0004",
        "evt-p017-base-0005",
        "evt-p017-surge-0001",
        "evt-p017-surge-0002",
        "evt-p017-surge-0003",
        "evt-p017-surge-0004",
        "evt-p017-surge-0005",
        "evt-p017-surge-0006",
        "evt-p017-surge-0007",
        "evt-p017-surge-0008",
    ]
    assert {event.sku for event in first} == {SKU}
    assert {event.event_type for event in first} == {"sale.completed"}
    assert {event.correlation_id for event in first} == {"run-weekend-demand-surge-1"}
    assert sum(event.quantity for event in first if event.event_id.startswith("evt-p017-base-")) == 50
    assert sum(event.quantity for event in first if event.event_id.startswith("evt-p017-surge-")) == 73


def test_committed_fixture_matches_the_seed() -> None:
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert document["seed"] == 1
    assert document["sku"] == SKU
    assert document["increase_min"] == "0.46"
    assert load_committed_surge() == reset_weekend_demand_surge()
    assert scenario_document()["events"] == document["events"]


def test_detection_is_a_forty_six_percent_spike() -> None:
    notice = detect_demand_surge(reset_weekend_demand_surge())

    assert notice is not None
    assert notice.baseline_units_per_hour == "12.5"
    assert notice.surge_units_per_hour == "18.25"
    assert notice.increase == "0.46"
    assert Decimal(notice.increase) >= Decimal("0.46")
    assert notice.event_ids == tuple(event.event_id for event in reset_weekend_demand_surge())


def test_another_sku_does_not_change_the_spike() -> None:
    extra = reset_weekend_demand_surge()[0].model_copy(update={"event_id": "evt-other", "sku": "P001"})

    assert detect_demand_surge((*reset_weekend_demand_surge(), extra)) == detect_demand_surge(
        reset_weekend_demand_surge()
    )


def test_a_repeated_event_id_does_not_double_the_velocity() -> None:
    events = reset_weekend_demand_surge()

    assert detect_demand_surge(events + events) == detect_demand_surge(events)


def test_a_conflicting_payload_is_rejected() -> None:
    events = list(reset_weekend_demand_surge())
    events.append(events[0].model_copy(update={"quantity": 11}))

    with pytest.raises(BackboneError, match="two payloads"):
        detect_demand_surge(events)


def test_a_smaller_surge_is_not_the_anomaly() -> None:
    events = []
    for event in reset_weekend_demand_surge():
        if event.event_id.startswith("evt-p017-surge-"):
            events.append(event.model_copy(update={"quantity": 1}))
        else:
            events.append(event)

    assert detect_demand_surge(events) is None


def test_other_seeds_are_refused() -> None:
    with pytest.raises(BackboneError, match="seed 1"):
        reset_weekend_demand_surge(2)


def test_three_replays_notify_the_same_spike_without_a_second_row() -> None:
    pipe = MemoryPipe()
    sink = MemorySink()
    ledger = MemoryLedger()
    quarantine = MemoryQuarantine()
    observer = RecordingObserver()

    notices = [
        replay_demand_surge(pipe, sink, ledger, quarantine, observer)
        for _ in range(3)
    ]

    assert notices[0] == notices[1] == notices[2]
    assert observer.notices == notices
    assert quarantine.records == []
    for event in reset_weekend_demand_surge():
        assert sink.count("sales_events", event.event_id) == 1
        assert sink.get("sales_events", event.event_id) == event


def test_publish_uses_one_store_events_command_per_sale() -> None:
    runner = FakeRunner()
    pipe = GcloudPipe(config_for_test(), runner)

    published = publish_demand_surge(pipe)

    assert len(published) == 13
    assert len(runner.commands) == 13
    for command, event in zip(runner.commands, published, strict=True):
        rendered = " ".join(command)
        assert command[:4] == ["gcloud", "pubsub", "topics", "publish"]
        assert "store-events" in command
        assert f"--ordering-key={event.event_id}" in command
        assert event.sku in rendered
        assert event.correlation_id in rendered


def test_publish_command_prints_the_event_ids(monkeypatch, capsys) -> None:
    runner = FakeRunner()

    class Pipe:
        def __init__(self, config, command_runner) -> None:
            del config, command_runner
            self.runner = runner

        def publish(self, event: StoreEvent) -> None:
            self.runner.run(["publish", event.event_id])

    monkeypatch.setattr("retailtwin_api.demand_surge.load_env_file", lambda path: None)
    monkeypatch.setattr("retailtwin_api.demand_surge.GcloudPipe", Pipe)
    monkeypatch.setattr("retailtwin_api.demand_surge.SubprocessRunner", lambda: object())

    assert main(["publish"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sku"] == SKU
    assert payload["correlation_id"] == "run-weekend-demand-surge-1"
    assert payload["published"] == [event.event_id for event in reset_weekend_demand_surge()]
    assert len(runner.commands) == 13


def test_publish_command_reports_a_refused_pipe(monkeypatch, capsys) -> None:
    class Pipe:
        def __init__(self, config, command_runner) -> None:
            del config, command_runner

        def publish(self, event: StoreEvent) -> None:
            del event
            raise BackboneError("Refusing topic other-topic.")

    monkeypatch.setattr("retailtwin_api.demand_surge.load_env_file", lambda path: None)
    monkeypatch.setattr("retailtwin_api.demand_surge.GcloudPipe", Pipe)
    monkeypatch.setattr("retailtwin_api.demand_surge.SubprocessRunner", lambda: object())

    assert main(["publish"]) == 1
    assert "Refusing topic" in capsys.readouterr().err


def test_a_missing_or_invalid_fixture_is_refused(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(BackboneError, match="Cannot read fixture"):
        load_committed_surge(missing)

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(BackboneError, match="Cannot read fixture"):
        load_committed_surge(broken)

    empty = tmp_path / "empty.json"
    empty.write_text('{"seed": 1}', encoding="utf-8")
    with pytest.raises(BackboneError, match="no events"):
        load_committed_surge(empty)

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"events": [{"event_id": ""}]}', encoding="utf-8")
    with pytest.raises(BackboneError, match="Cannot read fixture"):
        load_committed_surge(invalid)


def test_mixed_correlation_ids_are_refused() -> None:
    events = list(reset_weekend_demand_surge())
    events[0] = events[0].model_copy(update={"correlation_id": "run-other"})

    with pytest.raises(BackboneError, match="one correlation_id"):
        detect_demand_surge(events)


def test_sales_outside_both_windows_are_not_a_surge() -> None:
    event = reset_weekend_demand_surge()[0].model_copy(
        update={
            "occurred_at": datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
            "event_id": "evt-p017-old",
        }
    )

    assert detect_demand_surge((event,)) is None


def test_a_conflicting_claim_stops_the_replay() -> None:
    pipe = MemoryPipe()
    sink = MemorySink()
    ledger = MemoryLedger()
    quarantine = MemoryQuarantine()
    first = reset_weekend_demand_surge()[0].model_copy(update={"quantity": 11})
    pipe.publish(first)
    landed = deliver(pipe, sink, ledger, quarantine, pipe.pull(limit=1)[0])

    assert landed.outcome == "inserted"

    with pytest.raises(BackboneError, match="not accepted"):
        replay_demand_surge(pipe, sink, ledger, quarantine, RecordingObserver())


def test_replay_stops_when_the_spike_is_absent(monkeypatch) -> None:
    monkeypatch.setattr("retailtwin_api.demand_surge.detect_demand_surge", lambda events: None)

    with pytest.raises(BackboneError, match="not detected"):
        replay_demand_surge(
            MemoryPipe(),
            MemorySink(),
            MemoryLedger(),
            MemoryQuarantine(),
            RecordingObserver(),
        )


def test_env_file_ignores_a_missing_path(tmp_path) -> None:
    load_env_file(tmp_path / "absent.env")


def test_env_file_fills_missing_values_and_keeps_existing_ones(tmp_path, monkeypatch) -> None:
    path = tmp_path / ".env"
    path.write_text("GCP_PROJECT_ID=\"from-file\"\nNEW_SURGE_FLAG='yes'\n# note\n\n", encoding="utf-8")
    monkeypatch.setenv("GCP_PROJECT_ID", "already-set")
    monkeypatch.delenv("NEW_SURGE_FLAG", raising=False)

    load_env_file(path)

    assert os.environ["GCP_PROJECT_ID"] == "already-set"
    assert os.environ["NEW_SURGE_FLAG"] == "yes"


def config_for_test():
    from retailtwin_api.backbone import config_from_env

    return config_from_env(
        {
            "GCP_PROJECT_ID": "retailtwin-ai-511002",
            "GCP_REGION": "us-central1",
            "BIGQUERY_LOCATION": "us-central1",
        }
    )
