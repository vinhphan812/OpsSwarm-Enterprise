import pytest
from datetime import datetime, timezone, timedelta
from retailtwin_api.backbone import BackboneError
from retailtwin_api.backbone_gcp import _generation_field, _lease_held, _decode_body, _http_error

def test_generation_field():
    assert _generation_field({}) == 1
    assert _generation_field({"insert_generation": {"integerValue": "2"}}) == 2
    with pytest.raises(BackboneError, match="unreadable insert generation"):
        _generation_field({"insert_generation": "not a dict"})
    with pytest.raises(BackboneError, match="unreadable insert generation"):
        _generation_field({"insert_generation": {"integerValue": "0"}})

def test_lease_held():
    assert _lease_held(None) is True
    assert _lease_held(datetime.now(timezone.utc) + timedelta(seconds=10)) is True
    assert _lease_held(datetime.now(timezone.utc) - timedelta(seconds=10)) is False

def test_decode_body_extra():
    assert _decode_body(None) == ""
    assert _decode_body("!!invalid!!") == ""

def test_http_error_extra():
    err = _http_error("Fail", 400, '{"error": {"message": "bad"}}')
    assert "bad" in str(err)
    err = _http_error("Fail", 400, '{"error": {}}')
    assert "Fail failed with HTTP 400." in str(err)
    err = _http_error("Fail", 400, 'not-json')
    assert "not-json" in str(err)

from retailtwin_api.backbone import config_from_env, BackboneConfig, BackboneError
import os

def test_config_from_env_coverage():
    # Test valid env
    env = {
        "GCP_REGION": "us-central1",
        "BIGQUERY_LOCATION": "us-central1",
        "GCP_PROJECT_ID": "retailtwin-ai-511002",
    }
    cfg = config_from_env(env)
    assert cfg.project == "retailtwin-ai-511002"

    # Test differing region/location
    env_diff = {
        "GCP_REGION": "us-west1",
        "BIGQUERY_LOCATION": "us-central1",
    }
    with pytest.raises(BackboneError, match="GCP_REGION and BIGQUERY_LOCATION differ"):
        config_from_env(env_diff)

    # Test invalid topic
    env_invalid_topic = {"STORE_EVENTS_TOPIC": "bad-topic"}
    with pytest.raises(BackboneError, match="Refusing topic bad-topic"):
        config_from_env(env_invalid_topic)
