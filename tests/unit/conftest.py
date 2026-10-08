import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
import os

@pytest.fixture
def client():
    # Set required env vars *before* importing api to avoid module-level init failure
    os.environ["GITHUB_REPO"] = "owner/repo"
    import opsswarm.api as api_module
    
    orig_engine = api_module.engine
    orig_gh = api_module.gh
    orig_oc = api_module.oc

    mock_gh = MagicMock()
    mock_gh.create_issue = AsyncMock(
        return_value={"number": "1", "html_url": "https://github.com/test/repo/issues/1"}
    )
    mock_gh.permission = AsyncMock(return_value="write")
    mock_gh.comment = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.runs = {}
    mock_engine.start_issue = AsyncMock()
    mock_engine.handle_comment = AsyncMock()

    mock_oc = MagicMock()

    try:
        api_module.gh = mock_gh
        api_module.engine = mock_engine
        api_module.oc = mock_oc
        api_module.app.dependency_overrides.clear()
        yield TestClient(api_module.app)
    finally:
        api_module.engine = orig_engine
        api_module.gh = orig_gh
        api_module.oc = orig_oc
        api_module.app.dependency_overrides.clear()
