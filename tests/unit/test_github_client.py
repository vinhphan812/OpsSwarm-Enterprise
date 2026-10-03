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

            # Unexpected errors are sanitized to PermissionError (no raw internals leaked).
            with pytest.raises(PermissionError, match="GitHub API request failed"):
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

            result = await client.create_issue("New Issue", "Description", ["bug", "help wanted"])

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
            mock_r.content = b"{}"
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

            # Unexpected errors are sanitized to PermissionError (no raw internals leaked).
            with pytest.raises(PermissionError, match="GitHub API request failed"):
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

    # -------------------------------------------------------------------------
    # Additional method coverage: create_branch, open_pr, get_pr_status, merge_pr
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_branch_success(self, client):
        """create_branch resolves the source ref and posts a git ref."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            # GET /repos/owner/repo/git/ref/heads/main
            mock_source_r = MagicMock()
            mock_source_r.json.return_value = {"object": {"sha": "abc123"}}
            mock_source_r.content = b'{"object":{"sha":"abc123"}}'
            mock_source_r.raise_for_status = MagicMock()
            # PUT /repos/owner/repo/git/refs
            mock_branch_r = MagicMock()
            mock_branch_r.json.return_value = {"ref": "refs/heads/fix/x", "object": {"sha": "abc123"}}
            mock_branch_r.content = b'{"ref":"refs/heads/fix/x"}'
            mock_branch_r.raise_for_status = MagicMock()
            mock_request.side_effect = [mock_source_r, mock_branch_r]

            result = await client.create_branch("fix/x", "main")

            calls = mock_request.call_args_list
            assert len(calls) == 2
            # call objects: positional=(method, path), keyword=kwargs
            assert calls[0][0] == ("GET", "/repos/owner/repo/git/ref/heads/main")
            assert calls[1][0] == ("POST", "/repos/owner/repo/git/refs")
            assert calls[1][1]["json"] == {"ref": "refs/heads/fix/x", "sha": "abc123"}
            assert result["ref"] == "refs/heads/fix/x"

    @pytest.mark.asyncio
    async def test_create_branch_default_from_ref(self, client):
        """create_branch defaults from_ref to 'main'."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_source_r = MagicMock()
            mock_source_r.json.return_value = {"object": {"sha": "abc123"}}
            mock_source_r.content = b'{"object":{"sha":"abc123"}}'
            mock_source_r.raise_for_status = MagicMock()
            mock_branch_r = MagicMock()
            mock_branch_r.json.return_value = {"ref": "refs/heads/fix/x", "object": {"sha": "abc123"}}
            mock_branch_r.content = b'{"ref":"refs/heads/fix/x"}'
            mock_branch_r.raise_for_status = MagicMock()
            mock_request.side_effect = [mock_source_r, mock_branch_r]

            await client.create_branch("fix/x")  # no from_ref

            calls = mock_request.call_args_list
            assert "/git/ref/heads/main" in calls[0][0][1]

    @pytest.mark.asyncio
    async def test_open_pr_success(self, client):
        """open_pr posts a draft PR and returns PR data."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = {"number": 42, "html_url": "https://github.com/owner/repo/pull/42"}
            mock_r.content = b'{"number":42}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.open_pr("fix: resolve 500", "Fixes #1", "fix/x", "main", draft=True)

            mock_request.assert_called_once_with(
                "POST",
                "/repos/owner/repo/pulls",
                json={"title": "fix: resolve 500", "body": "Fixes #1", "head": "fix/x", "base": "main", "draft": True},
            )
            assert result["number"] == 42

    @pytest.mark.asyncio
    async def test_open_pr_default_draft(self, client):
        """open_pr defaults draft=True."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = {"number": 1}
            mock_r.content = b'{"number":1}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            await client.open_pr("title", "body", "head", "base")  # no draft arg

            _, kwargs = mock_request.call_args
            assert kwargs["json"]["draft"] is True

    @pytest.mark.asyncio
    async def test_get_pr_status_success_checks_passed(self, client):
        """get_pr_status returns checks_state=success when all checks pass."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_pr_r = MagicMock()
            mock_pr_r.json.return_value = {
                "state": "open", "merged": False, "mergeable": True, "head": {"sha": "abc123"}
            }
            mock_pr_r.content = b'{"state":"open"}'
            mock_pr_r.raise_for_status = MagicMock()
            mock_checks_r = MagicMock()
            mock_checks_r.json.return_value = {
                "check_runs": [
                    {"conclusion": "success"},
                    {"conclusion": "success"},
                ]
            }
            mock_checks_r.content = b'{"check_runs":[...]}'
            mock_checks_r.raise_for_status = MagicMock()
            mock_request.side_effect = [mock_pr_r, mock_checks_r]

            result = await client.get_pr_status(42)

            assert result["checks_state"] == "success"
            assert result["state"] == "open"
            assert result["merged"] is False
            assert result["mergeable"] is True

    @pytest.mark.asyncio
    async def test_get_pr_status_failure_check(self, client):
        """get_pr_status returns checks_state=failure on a failed check."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_pr_r = MagicMock()
            mock_pr_r.json.return_value = {
                "state": "open", "merged": False, "mergeable": True, "head": {"sha": "abc123"}
            }
            mock_pr_r.content = b'{"state":"open"}'
            mock_pr_r.raise_for_status = MagicMock()
            mock_checks_r = MagicMock()
            mock_checks_r.json.return_value = {
                "check_runs": [{"conclusion": "success"}, {"conclusion": "failure"}]
            }
            mock_checks_r.content = b'{"check_runs":[...]}'
            mock_checks_r.raise_for_status = MagicMock()
            mock_request.side_effect = [mock_pr_r, mock_checks_r]

            result = await client.get_pr_status(42)

            assert result["checks_state"] == "failure"

    @pytest.mark.asyncio
    async def test_get_pr_status_cancelled_check(self, client):
        """get_pr_status returns checks_state=failure on a cancelled check."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_pr_r = MagicMock()
            mock_pr_r.json.return_value = {
                "state": "open", "merged": False, "mergeable": True, "head": {"sha": "abc123"}
            }
            mock_pr_r.content = b'{"state":"open"}'
            mock_pr_r.raise_for_status = MagicMock()
            mock_checks_r = MagicMock()
            mock_checks_r.json.return_value = {
                "check_runs": [{"conclusion": "cancelled"}]
            }
            mock_checks_r.content = b'{"check_runs":[...]}'
            mock_checks_r.raise_for_status = MagicMock()
            mock_request.side_effect = [mock_pr_r, mock_checks_r]

            result = await client.get_pr_status(42)

            assert result["checks_state"] == "failure"

    @pytest.mark.asyncio
    async def test_get_pr_status_pending_check(self, client):
        """get_pr_status returns checks_state=pending when no conclusion yet."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_pr_r = MagicMock()
            mock_pr_r.json.return_value = {
                "state": "open", "merged": False, "mergeable": True, "head": {"sha": "abc123"}
            }
            mock_pr_r.content = b'{"state":"open"}'
            mock_pr_r.raise_for_status = MagicMock()
            mock_checks_r = MagicMock()
            mock_checks_r.json.return_value = {
                "check_runs": [{"conclusion": None}, {"conclusion": "success"}]
            }
            mock_checks_r.content = b'{"check_runs":[...]}'
            mock_checks_r.raise_for_status = MagicMock()
            mock_request.side_effect = [mock_pr_r, mock_checks_r]

            result = await client.get_pr_status(42)

            assert result["checks_state"] == "pending"

    @pytest.mark.asyncio
    async def test_get_pr_status_no_sha(self, client):
        """get_pr_status handles PR with no head SHA gracefully."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_pr_r = MagicMock()
            mock_pr_r.json.return_value = {"state": "open", "merged": False, "mergeable": None, "head": None}
            mock_pr_r.content = b'{"state":"open"}'
            mock_pr_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_pr_r

            result = await client.get_pr_status(42)

            assert result["checks_state"] == "pending"
            assert result["head_sha"] is None

    @pytest.mark.asyncio
    async def test_merge_pr_success(self, client):
        """merge_pr returns merge result."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = {"merged": True, "sha": "def456"}
            mock_r.content = b'{"merged":true}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            result = await client.merge_pr(42, merge_method="squash")

            mock_request.assert_called_once_with(
                "PUT",
                "/repos/owner/repo/pulls/42/merge",
                json={"merge_method": "squash"},
            )
            assert result["merged"] is True

    @pytest.mark.asyncio
    async def test_merge_pr_default_merge_method(self, client):
        """merge_pr defaults merge_method to 'squash'."""
        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.json.return_value = {"merged": True}
            mock_r.content = b'{"merged":true}'
            mock_r.raise_for_status = MagicMock()
            mock_request.return_value = mock_r

            await client.merge_pr(42)  # no merge_method

            _, kwargs = mock_request.call_args
            assert kwargs["json"]["merge_method"] == "squash"

    @pytest.mark.asyncio
    async def test_http_status_error_sanitized(self, client):
        """HTTPStatusError is caught and re-raised as a sanitized PermissionError."""
        import httpx

        with patch.object(client.client, "request", new_callable=AsyncMock) as mock_request:
            mock_r = MagicMock()
            mock_r.status_code = 403
            mock_r.text = "token_invalid_internal_path_data"
            # Simulate httpx.HTTPStatusError
            exc = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=mock_r)
            mock_request.side_effect = exc

            with pytest.raises(PermissionError, match="GitHub API returned 403"):
                await client._req("GET", "/repos/owner/repo/secret")
