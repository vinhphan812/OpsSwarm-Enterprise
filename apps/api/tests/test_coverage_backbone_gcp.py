import pytest
import json
from unittest.mock import MagicMock, patch
from retailtwin_api.backbone import BackboneError, InsertJobFailed, BackboneConfig
from retailtwin_api.backbone_gcp import _decode_body, BigQuerySink, FirestoreRest, BackboneError, _precondition_failed, _http_error, _ClaimSnapshot, _optional_string, HttpResponse, parse_pull_output, GcloudPipe, qualified_table, parameter_flag, _job_id_ok

def test_decode_body():
    assert _decode_body("") == ""
    assert _decode_body(123) == ""
    assert _decode_body("SGVsbG8=") == "Hello"
    assert _decode_body("invalid-base64!") == ""

def test_bigquery_sink_join_existing_job_errors():
    class MockRunner:
        def __init__(self, raw_resp):
            self.raw_resp = raw_resp
        def run(self, args: list[str]) -> str:
            if "wait" in args:
                return ""
            return self.raw_resp

    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "proj"
    config.location = "loc"
    
    # 1. Invalid JSON
    runner = MockRunner("invalid")
    sink = BigQuerySink(config, runner)
    with pytest.raises(BackboneError, match="BigQuery job status was not JSON"):
        sink._join_existing_job("job1")

    # 2. Status missing/not done
    runner = MockRunner("{}")
    sink = BigQuerySink(config, runner)
    with pytest.raises(BackboneError, match="Insert job is still running"):
        sink._join_existing_job("job1")
    
    # 3. Status state != DONE
    runner = MockRunner('{"status": {"state": "PENDING"}}')
    sink = BigQuerySink(config, runner)
    with pytest.raises(BackboneError, match="Insert job is still running"):
        sink._join_existing_job("job1")

    # 4. ErrorResult present
    runner = MockRunner('{"status": {"state": "DONE", "errorResult": {"message": "failed"}}}')
    sink = BigQuerySink(config, runner)
    with pytest.raises(InsertJobFailed):
        sink._join_existing_job("job1")

def test_http_error_handling():
    assert _precondition_failed(409, "") is True
    assert _precondition_failed(400, '{"error": {"status": "FAILED_PRECONDITION"}}') is True
    assert _precondition_failed(400, '{"error": {"status": "ALREADY_EXISTS"}}') is True
    assert _precondition_failed(500, "") is False
    assert _precondition_failed(400, "invalid") is False
    assert _precondition_failed(400, '{"error": 1}') is False

    err = _http_error("Action", 500, '{"error": {"message": "oops"}}')
    assert "Action failed with HTTP 500. oops" in str(err)
    
    err = _http_error("Action", 500, "plain text error")
    assert "Action failed with HTTP 500. plain text error" in str(err)

def test_firestore_rest_acquire_landing_coverage():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "proj"
    runner = MagicMock()
    fs = FirestoreRest(config, runner)
    
    # Unknown state
    with patch.object(fs, "_read_snapshot") as mock_read:
        mock_read.return_value = _ClaimSnapshot("1", "t", "c", "unknown", None, 1)
        with pytest.raises(BackboneError, match="unknown state"):
            fs.acquire_landing("e1")

    # Success
    with patch.object(fs, "_read_snapshot") as mock_read:
        with patch.object(fs, "_call") as mock_call:
            mock_read.return_value = _ClaimSnapshot("1", "t", "c", "claimed", None, 1)
            mock_call.return_value = MagicMock(status=200, body='{"writeResults": [{"updateTime": "2"}]}')
            res = fs.acquire_landing("e1")
            assert res is not None

def test_firestore_rest_fail_insert_coverage():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "proj"
    runner = MagicMock()
    fs = FirestoreRest(config, runner)
    
    assert fs.fail_insert("e1", None, 1) is None
    assert fs.fail_insert("e1", "f", 0) is None
    
def test_firestore_rest_transition_coverage():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "proj"
    runner = MagicMock()
    fs = FirestoreRest(config, runner)
    
    with pytest.raises(BackboneError, match="Lost the landing lease"):
        fs._transition("e1", None, "state", "action")

def test_firestore_rest_mark_landed_coverage():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "proj"
    runner = MagicMock()
    fs = FirestoreRest(config, runner)
    
    with pytest.raises(BackboneError, match="Lost the landing lease"):
        fs.mark_landed("e1", None)

def test_qualified_table_coverage():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "p"
    config.dataset = "d"
    assert qualified_table(config, "sales_events") == "`p.d.sales_events`"

def test_parameter_flag_coverage():
    assert parameter_flag("a", "b", "c") == "--parameter=a:b:c"

def test_others_coverage():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    config.project = "p"
    config.dataset = "d"
    assert qualified_table(config, "sales_events") == "`p.d.sales_events`"
    assert parameter_flag("a", "b", "c") == "--parameter=a:b:c"
    assert _job_id_ok("a" * 1024) is True
    assert _job_id_ok("a_b-1") is True
    assert _optional_string({}, "a") is None

def test_parse_pull_output_coverage():
    with pytest.raises(BackboneError, match="missing an ack id"):
        parse_pull_output('[{"message":{}}]')
    
    res = parse_pull_output('[{"ackId":"1", "message": {"data": "SGVsbG8="}}]')
    assert len(res) == 1
    assert res[0].body == "Hello"

def test_gcloud_pipe_coverage():
    config = MagicMock(spec=BackboneConfig)
    config.validated.return_value = config
    runner = MagicMock()
    runner.run.return_value = "token"
    pipe = GcloudPipe(config, runner)
    
    pipe.ack("id")
    assert runner.run.called
