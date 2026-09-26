import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

def test_issue_comment_created():
    import opsswarm.api as api_module
    
    orig_gh = api_module.gh
    orig_verify = api_module.verify_signature
    api_module.verify_signature = lambda *args: True
    
    try:
        mock_gh = MagicMock()
        mock_gh.permission = AsyncMock(return_value="write")
        api_module.gh = mock_gh
        
        mock_engine = MagicMock()
        mock_engine.handle_comment = AsyncMock()
        api_module.engine = mock_engine
        
        client = TestClient(api_module.app)
        response = client.post(
            "/webhooks/github",
            json={
                "action": "created",
                "issue": {"number": 1},
                "comment": {"id": 123, "user": {"login": "user1"}, "body": "/test"}
            },
            headers={"x-github-event": "issue_comment", "x-hub-signature-256": "sha256=abc"}
        )
        assert response.status_code == 200
        assert response.json()["accepted"] is True
        mock_engine.handle_comment.assert_called_once()
    finally:
        api_module.gh = orig_gh
        api_module.verify_signature = orig_verify
