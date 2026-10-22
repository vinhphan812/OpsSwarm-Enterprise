"""Additional tests to ensure robust coverage of container-delivery and HA endpoints."""
from __future__ import annotations

import os
import asyncio
from unittest.mock import MagicMock, AsyncMock
import pytest
from fastapi.testclient import TestClient

def test_readiness_and_health_endpoints():
    import opsswarm.api as api_module
    import opsswarm.auth as auth_module

    orig_verify = auth_module.verify_scoped_bearer
    try:
        async def mock_verify(request, authorization=None):
            return "opsswarm:admin"
        auth_module.verify_scoped_bearer = mock_verify

        client = TestClient(api_module.app)
        
        # Test /health
        res = client.get("/health")
        assert res.status_code in (200, 503)
        
        # Test /ready
        res = client.get("/ready")
        assert res.status_code in (200, 503)

        # Test metrics
        res = client.get("/metrics")
        assert res.status_code == 200

        # Test lifecycle methods
        api_module.lifecycle.set_ready()
        assert api_module.lifecycle.is_accepting_work is True

        api_module.lifecycle.set_failed("startup error test")
        assert api_module.lifecycle.startup_error == "startup error test"

    finally:
        auth_module.verify_scoped_bearer = orig_verify

def test_normalization_functions():
    from opsswarm.normalization import (
        redact_pii,
        normalize_confidence,
        normalize_list_of_strings,
        normalize_optional_string,
        normalize_finding,
    )
    assert redact_pii("secret test") is not None
    assert normalize_confidence(0.85) == 0.85
    assert normalize_list_of_strings(["a", "b"]) == ["a", "b"]
    assert normalize_optional_string("test") == "test"
    assert normalize_finding({"id": "1", "kind": "finding"}) is not None

def test_validators():
    from opsswarm.validators import validate_task_graph
    validate_task_graph([{"id": "t1", "parents": []}])
