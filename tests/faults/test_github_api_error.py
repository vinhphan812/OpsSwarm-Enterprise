import pytest
from unittest.mock import AsyncMock, patch
import httpx
from opsswarm.github_client import GitHubClient

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_api_error_handling():
    """Verify handling when GitHub API returns error (e.g., 500)."""
    client = GitHubClient(token="fake", repo="owner/repo")
    
    with patch.object(client.client, "request", new_callable=AsyncMock) as mock_req:
        response = httpx.Response(500, content=b"Internal Server Error")
        response.request = httpx.Request("GET", "https://api.github.com/repos/owner/repo/issues/1")
        mock_req.return_value = response
        
        # _req() sanitizes HTTPStatusError into PermissionError (C-11 fix)
        with pytest.raises(PermissionError):
            await client.get_issue(1)
