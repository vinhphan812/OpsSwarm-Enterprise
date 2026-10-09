import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
import opsswarm.runtime

def test_ready_startup_endpoint(client):
    """Verify /ready returns 503 while not ready."""
    # Readiness starts False by default
    opsswarm.runtime.readiness._is_ready = False
    response = client.get("/ready")
    assert response.status_code == 503

    # Manually set to ready for test
    opsswarm.runtime.readiness._is_ready = True
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["ok"] is True

def test_draining_blocks_mutations(client):
    """Verify @check_draining blocks POST requests when draining."""
    import opsswarm.runtime
    opsswarm.runtime.readiness._is_draining = True
    
    # Test monitoring hook
    response = client.post("/hooks/monitoring", json={})
    assert response.status_code == 503
    assert response.json()["detail"] == "Service is draining"
    
    # Test resume hook
    # Need auth for this one
    import time
    from tests.unit.test_api import _generate_bearer, _auth_header
    now = int(time.time())
    token = _generate_bearer("opsswarm:write", "test-secret", "POST", "/runs/1/resume", timestamp=now)
    
    response = client.post("/runs/1/resume", headers=_auth_header(token))
    assert response.status_code == 503

def test_on_shutdown_handler():
    """Verify shutdown sets draining state."""
    import opsswarm.api as api_module
    import asyncio
    
    opsswarm.runtime.readiness._is_ready = True
    opsswarm.runtime.readiness._is_draining = False
    
    # Simulate shutdown
    asyncio.run(api_module._shutdown_drain())
    
    assert opsswarm.runtime.readiness.draining is True
    assert opsswarm.runtime.readiness.ready is False
