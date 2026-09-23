"""Unit tests for opsswarm.github_client module."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opsswarm.github_client import GitHubClient


class TestGitHubClient:
    """Tests for GitHubClient class."""

    @pytest.fixture
    def client(self):
        """Create a GitHubClient instance for testing."""
        return GitHubClient(token="test-token", repo="owner/repo")

    def test_init_sets_repo(self, client):
        """Client stores the repo name."""
        assert client.repo == "owner/repo"

    def test_init_creates_httpx_client(self, client):
        """Client creates an httpx AsyncClient."""
        assert client.client is not None
        assert "Authorization" in client.client.headers
        assert "Bearer test-token" in client.client.headers["Authorization"]
        assert client.client.headers["Accept"] == "application/vnd.github+json"

    def test_init_custom_base_url(self):
        """Client can use custom base URL."""
        client = GitHubClient(
            token="token", repo="owner/repo", base_url="https://github.example.com/api/v3"
        )
        # Check that the client was created with the custom URL
        assert "github.example.com" in str(client.client.base_url)

    @pytest.mark.asyncio
    async def test_get_issue_success(self, client):
        """get_issue returns issue data."""
        mock_response = {"number": 123, "title": "Test Issue", "state": "open"}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{"number": 123}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.get_issue(123)

            mock_request.assert_called_once_with("GET", "/repos/owner/repo/issues/123")
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_get_issue_not_found(self, client):
        """get_issue raises on 404."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.status_code = 404
            mock_r.raise_for_status.side_effect = Exception("Not found")
            mock_request.return_value = mock_r

            with pytest.raises(Exception, match="Not found"):
                await client.get_issue(999)

    @pytest.mark.asyncio
    async def test_comment_success(self, client):
        """comment posts to issues endpoint."""
        mock_response = {"id": 1, "body": "Test comment"}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{"id": 1}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.comment(123, "Test comment")

            mock_request.assert_called_once_with(
                "POST",
                "/repos/owner/repo/issues/123/comments",
                json={"body": "Test comment"},
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_set_labels_success(self, client):
        """set_labels posts labels to issue."""
        mock_response = [{"name": "bug"}, {"name": "priority"}]

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'[{"name": "bug"}]'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.set_labels(123, ["bug", "priority"])

            mock_request.assert_called_once_with(
                "POST",
                "/repos/owner/repo/issues/123/labels",
                json={"labels": ["bug", "priority"]},
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_close_issue_success(self, client):
        """close_issue patches issue to closed state."""
        mock_response = {"number": 123, "state": "closed"}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{"number": 123}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.close_issue(123)

            mock_request.assert_called_once_with(
                "PATCH",
                "/repos/owner/repo/issues/123",
                json={"state": "closed", "state_reason": "completed"},
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_create_issue_success(self, client):
        """create_issue posts new issue."""
        mock_response = {"number": 456, "title": "New Issue", "body": "Description"}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{"number": 456}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.create_issue(
                "New Issue", "Description", ["bug", "help wanted"]
            )

            mock_request.assert_called_once_with(
                "POST",
                "/repos/owner/repo/issues",
                json={
                    "title": "New Issue",
                    "body": "Description",
                    "labels": ["bug", "help wanted"],
                },
            )
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_permission_admin(self, client):
        """permission returns admin for admin users."""
        mock_response = {"permission": "admin"}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{"permission": "admin"}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.permission("admin_user")

            mock_request.assert_called_once_with(
                "GET", "/repos/owner/repo/collaborators/admin_user/permission"
            )
            assert result == "admin"

    @pytest.mark.asyncio
    async def test_permission_read(self, client):
        """permission returns read for reader users."""
        mock_response = {"permission": "read"}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{"permission": "read"}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.permission("reader_user")

            assert result == "read"

    @pytest.mark.asyncio
    async def test_permission_not_collaborator(self, client):
        """permission returns none for non-collaborators."""
        mock_response = {"permission": "none"}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{"permission": "none"}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.permission("outsider")

            assert result == "none"

    @pytest.mark.asyncio
    async def test_permission_missing_key(self, client):
        """permission returns none when permission key is missing."""
        mock_response = {}

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = mock_response
            mock_r.content = b'{}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.permission("someuser")

            assert result == "none"

    @pytest.mark.asyncio
    async def test_http_error_handling(self, client):
        """HTTP errors propagate through raise_for_status."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.status_code = 403
            mock_r.raise_for_status.side_effect = Exception("Forbidden")
            mock_request.return_value = mock_r

            with pytest.raises(Exception, match="Forbidden"):
                await client.get_issue(123)

    @pytest.mark.asyncio
    async def test_empty_response_content(self, client):
        """Empty response content returns None."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.content = b""
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client._req("GET", "/test")

            assert result is None
