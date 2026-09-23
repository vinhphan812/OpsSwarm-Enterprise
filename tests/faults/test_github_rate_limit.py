import pytest
from unittest.mock import AsyncMock, patch
import httpx
from opsswarm.github_client import GitHubClient

@pytest.mark.fault
@pytest.mark.asyncio
async def test_github_rate_limit_handling():
    """Verify handling when GitHub rate limit hit (429)."""
    client = GitHubClient(token="fake", repo="owner/repo")
    
    with patch.object(client.client, "request", new_callable=AsyncMock) as mock_req:
        response = httpx.Response(429, content=b"Too Many Requests")
        response.request = httpx.Request("GET", "https://api.github.com/repos/owner/repo/issues/1")
        mock_req.return_value = response
        
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_issue(1)
