import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from retailtwin_api.backbone import BackboneError, BackboneConfig, PulledMessage, config_from_env
from retailtwin_api.backbone_gcp import SubprocessRunner, qualified_table, parse_query_output, parse_pull_output, FirestoreRest, HttpResponse, parameter_flag, _job_id_ok, BigQuerySink
from retailtwin_api.schemas import StoreEvent

def test_subprocess_runner_run_success():
    runner = SubprocessRunner()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="success\n", stderr="")
        result = runner.run(["true"])
        assert result == "success\n"
        mock_run.assert_called_once()

def test_subprocess_runner_run_failure():
    runner = SubprocessRunner()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="failed\n")
        with pytest.raises(BackboneError, match="failed"):
            runner.run(["false"])
        mock_run.assert_called_once()

def test_qualified_table_unknown():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    with pytest.raises(BackboneError, match="Unknown table"):
        qualified_table(config, "invalid")

def test_parse_query_output_empty():
    assert parse_query_output("") == []

def test_parse_query_output_invalid():
    with pytest.raises(BackboneError, match="BigQuery did not return JSON"):
        parse_query_output("invalid")

def test_parse_query_output_none():
    assert parse_query_output("null") == []

def test_parse_query_output_list():
    assert parse_query_output("[1, 2]") == [1, 2]

def test_parse_pull_output_invalid():
    with pytest.raises(BackboneError, match="Pub/Sub pull did not return JSON"):
        parse_pull_output("invalid")

def test_firestore_rest_claim_error():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "proj"
    runner = MagicMock()
    transport = MagicMock()
    # Simulate HTTP Error
    transport.request.return_value = MagicMock(status=500, body="error")

    fs = FirestoreRest(config, runner, transport=transport)
    event = StoreEvent(
        event_id="e1",
        correlation_id="c1",
        event_type="sale",
        store_id="s1",
        sku="sku1",
        quantity=1,
        occurred_at=datetime.now(timezone.utc),
        source="pos"
    )

    with pytest.raises(BackboneError, match="Claiming the event id failed with HTTP 500"):
        fs.claim(event, "sales_events")

def test_firestore_rest_record():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "proj"
    runner = MagicMock()
    transport = MagicMock()
    # Mocking successful response
    transport.request.return_value = HttpResponse(200, "{}")

    fs = FirestoreRest(config, runner, transport=transport)
    message = MagicMock(spec=PulledMessage)
    message.body = "data"
    message.attributes = {"key": "value"}

    fs.record(message, "reason")
    transport.request.assert_called_once()

def test_parameter_flag_error():
    with pytest.raises(BackboneError, match="contains a newline"):
        parameter_flag("name", "type", "value\n")

def test_job_id_ok_invalid():
    assert _job_id_ok("") is False
    assert _job_id_ok("a" * 1025) is False
    assert _job_id_ok("job!id") is False

def test_parse_query_output_unexpected():
    with pytest.raises(BackboneError, match="BigQuery returned an unexpected payload"):
        parse_query_output('{"a": 1}')

def test_parse_pull_output_unexpected():
    with pytest.raises(BackboneError, match="Pub/Sub pull returned an unexpected payload"):
        parse_pull_output('{"a": 1}')

def test_parse_pull_output_unexpected_message():
    with pytest.raises(BackboneError, match="Pub/Sub pull returned an unexpected message"):
        parse_pull_output('[1]')

def test_parse_pull_output_missing_ack_id():
    with pytest.raises(BackboneError, match="Pub/Sub pull is missing an ack id"):
        parse_pull_output('[{"message": {}}]')

def test_parse_pull_output_invalid_message():
    with pytest.raises(BackboneError, match="Pub/Sub pull returned an unexpected message"):
        parse_pull_output('[{"ackId": "1", "message": 1}]')

class FakeRunner:
    def __init__(self, output: str = "") -> None:
        self.commands: list[list[str]] = []
        self.output = output

    def run(self, args: list[str]) -> str:
        self.commands.append(args)
        return self.output

def test_bigquery_sink_count():
    runner = FakeRunner('[{"row_count": 1}]')
    sink = BigQuerySink(config_from_env({}), runner)
    assert sink.count("sales_events", "e1") == 1

    runner.output = '[{"row_count": 0}]'
    assert sink.count("sales_events", "e1") == 0

def test_bigquery_sink_insert_already_exists():
    class AlreadyExistsRunner:
        def run(self, args: list[str]) -> str:
            raise BackboneError("Already Exists")

    from retailtwin_api.schemas import StoreEvent
    from datetime import datetime, timezone

    evt = StoreEvent(
        event_id="e1",
        correlation_id="c1",
        event_type="sale.completed",
        store_id="s1",
        sku="sku1",
        quantity=1,
        occurred_at=datetime.now(timezone.utc),
        source="pos"
    )

    sink = BigQuerySink(config_from_env({}), AlreadyExistsRunner())
    with patch.object(sink, "_join_existing_job") as mock_join:
        sink.insert("sales_events", evt, "job-1")
        mock_join.assert_called_once_with("job-1")

def test_decode_body():
    from retailtwin_api.backbone_gcp import _decode_body
    import base64

    assert _decode_body("hello") == ""
    assert _decode_body(base64.b64encode(b"world").decode("utf-8")) == "world"
    assert _decode_body(123) == ""

def test_http_error():
    from retailtwin_api.backbone_gcp import _http_error

    err = _http_error("action", 400, '{"error": {"message": "bad request"}}')
    assert "bad request" in str(err)

    err = _http_error("action", 400, "plain text")
    assert "plain text" in str(err)

def test_precondition_failed():
    from retailtwin_api.backbone_gcp import _precondition_failed

    assert _precondition_failed(409, "{}") is True
    assert _precondition_failed(400, '{"error": {"status": "FAILED_PRECONDITION"}}') is True
    assert _precondition_failed(400, '{"error": {"status": "OTHER"}}') is False
    assert _precondition_failed(500, "{}") is False
