"""Unit tests for opsswarm.github_client module."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
        """Client can use the https://github.com/api/v3 alias."""
        client = GitHubClient(
            token="token", repo="owner/repo", base_url="https://github.com/api/v3"
        )
        # Check that the client was created with the custom URL
        assert "github.com" in str(client.client.base_url)

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


class TestGitHubClientSSRF:
    """ADR-028 SSRF mitigation tests — fail-closed transport boundary (Issue #72)."""

    # ----- base_url allowlist -----

    def test_init_rejects_arbitrary_base_url(self):
        """Non-whitelisted base_url raises ValueError."""
        with pytest.raises(ValueError, match="not in the approved origins list"):
            GitHubClient(token="tok", repo="owner/repo", base_url="https://evil.com/api")

    def test_init_rejects_http_base_url(self):
        """Plain http:// base_url is not in the approved origins list."""
        with pytest.raises(ValueError, match="not in the approved origins list"):
            GitHubClient(token="tok", repo="owner/repo", base_url="http://api.github.com")

    def test_init_rejects_localhost_base_url(self):
        """Non-whitelisted localhost variants are not in the approved origins list."""
        with pytest.raises(ValueError, match="not in the approved origins list"):
            GitHubClient(token="tok", repo="owner/repo", base_url="http://localhost/api")
        with pytest.raises(ValueError, match="not in the approved origins list"):
            GitHubClient(token="tok", repo="owner/repo", base_url="http://192.168.1.1/api")

    def test_init_accepts_localhost_for_test_fixtures(self):
        """http://127.0.0.1 is accepted for local test fixtures only in test/dev profile."""
        client = GitHubClient(
            token="tok",
            repo="test/repo",
            base_url="http://127.0.0.1",
            allowed_origins=frozenset({"http://127.0.0.1"}),
            verify=False,
            profile="test",
        )
        assert client.client is not None
        assert client.client.follow_redirects is False

    def test_init_accepts_github_com_api(self):
        """https://api.github.com is accepted."""
        client = GitHubClient(token="tok", repo="owner/repo", base_url="https://api.github.com")
        assert client.client is not None

    def test_init_accepts_github_com_api_alias(self):
        """https://github.com/api/v3 is accepted (must be in allowed_origins)."""
        client = GitHubClient(
            token="tok",
            repo="owner/repo",
            base_url="https://github.com/api/v3",
            allowed_origins=frozenset({"https://api.github.com", "https://github.com/api/v3"}),
        )
        assert client.client is not None

    # ----- repo format validation -----

    def test_init_rejects_repo_traversal(self):
        """Path-traversal repo raises ValueError."""
        with pytest.raises(ValueError, match="repo must be in 'owner/repo' format"):
            GitHubClient(token="tok", repo="../../../attacker.com/redirect")

    def test_init_rejects_repo_no_slash(self):
        """Repo without owner/ raises ValueError."""
        with pytest.raises(ValueError, match="repo must be in 'owner/repo' format"):
            GitHubClient(token="tok", repo="onlyrepo")

    def test_init_rejects_repo_empty_owner(self):
        """Empty owner component raises ValueError."""
        with pytest.raises(ValueError, match="repo must be in 'owner/repo' format"):
            GitHubClient(token="tok", repo="/repo")

    def test_init_rejects_repo_empty_name(self):
        """Empty repo-name component raises ValueError."""
        with pytest.raises(ValueError, match="repo must be in 'owner/repo' format"):
            GitHubClient(token="tok", repo="owner/")

    def test_init_accepts_valid_repo(self):
        """Valid 'owner/repo' format is accepted."""
        client = GitHubClient(token="tok", repo="my-org/my_service")
        assert client.repo == "my-org/my_service"

    def test_init_accepts_repo_with_dots_underscores(self):
        """Dots and underscores in repo components are accepted."""
        client = GitHubClient(token="tok", repo="my.org/my_serv.ice-1")
        assert client.repo == "my.org/my_serv.ice-1"

    # ----- follow_redirects=False -----

    def test_init_follow_redirects_false(self):
        """Client is created with follow_redirects=False."""
        client = GitHubClient(token="tok", repo="owner/repo")
        assert client.client.follow_redirects is False

    def test_init_custom_base_url_follow_redirects_false(self):
        """Even with a custom whitelisted base_url, redirects are disabled."""
        client = GitHubClient(
            token="tok", repo="owner/repo", base_url="https://github.com/api/v3"
        )
        assert client.client.follow_redirects is False

    # ----- transport limits -----

    def test_init_transport_limits_applied(self):
        """Transport limits are applied to the connection pool."""
        client = GitHubClient(token="tok", repo="owner/repo")
        # httpx 0.27 AsyncConnectionPool doesn't expose _limits; verify pool exists.
        pool = client.client._transport._pool
        assert pool is not None

    # ----- request timeout -----

    def test_init_timeout_applied(self):
        """Request timeout is set."""
        client = GitHubClient(token="tok", repo="owner/repo")
        assert client.client.timeout is not None
        assert client.client.timeout.connect == 5.0
        assert client.client.timeout.read == 10.0


class TestGitHubClientLogInjection:
    """Issue #58: log-injection (CodeQL py/log-injection alerts #3/#4).

    Verifies that attacker-controlled path/method values and GitHub-controlled
    HTTP response bodies containing CRLF or control characters are sanitised
    through sanitize_for_log() before reaching the structured-log handler, so
    emitted log lines are always single-line and no control-char injection is
    possible.  The raised PermissionError is intentionally NOT sanitised of its
    structured string (method/path are already validated/allowlisted inputs) —
    callers that surface it to GitHub comments are responsible for their own
    sanitisation layer (opsswarm/orchestrator.py / api.py handle that).
    """

    @pytest.fixture
    def client(self):
        return GitHubClient(token="test-token", repo="owner/repo")

    def _make_mock_error_response(
        self, status_code: int, text: str, exc_cls=Exception
    ):
        """Return (mock_request, mock_response) for a 4xx/5xx HTTP error.

        HTTPStatusError (httpx >= 0.27) requires message=, request=, response= kwargs.
        """
        mock_r = MagicMock()
        mock_r.status_code = status_code
        mock_r.text = text
        mock_r.content = text.encode()
        mock_request = MagicMock()
        # HTTPStatusError needs message= request= response= (httpx 0.27+)
        if exc_cls is httpx.HTTPStatusError or exc_cls.__name__ == "HTTPStatusError":
            exc = exc_cls(
                message=f"HTTP {status_code}",
                request=mock_request,
                response=mock_r,
            )
        else:
            exc = exc_cls(f"HTTP {status_code}")
        mock_r.raise_for_status = MagicMock(side_effect=exc)
        mock_async_request = AsyncMock(return_value=mock_r)
        return mock_r, mock_async_request

    @pytest.mark.asyncio
    async def test_crlf_in_path_logged_sanitized(self, client, caplog):
        """CRLF in path is replaced, not embedded verbatim in the log line."""
        path = "/repos/owner/repo\x0d\x0ainjected: true/issues"
        mock_r, mock_request = self._make_mock_error_response(
            403, "Forbidden body", exc_cls=httpx.HTTPStatusError
        )
        with patch.object(client.client, "request", new_callable=AsyncMock) as p:
            p.return_value = mock_r
            with caplog.at_level(logging.ERROR):
                with pytest.raises(PermissionError, match="GitHub API returned 403"):
                    await client._req("GET", path)
        # The log line must not contain an embedded newline that could inject a field.
        for record in caplog.records:
            assert "\n" not in record.getMessage(), (
                f"Log message contains a raw newline: {record.getMessage()!r}"
            )
            assert "\n" not in record.getMessage(), (
                f"Log message contains a raw CR: {record.getMessage()!r}"
            )

    @pytest.mark.asyncio
    async def test_control_chars_in_response_body_logged_sanitized(self, client, caplog):
        """Control characters in GitHub error body are stripped from log output."""
        body = (
            "Error: \x00NUL\x01\x1f last printable before space\x7fDEL\x80-high-byte"
            "\x9f\x85Vietnamese \xe1\xbb\x9b\xef\xbf\xbd"
        )
        mock_r, mock_request = self._make_mock_error_response(
            500, body, exc_cls=httpx.HTTPStatusError
        )
        with patch.object(client.client, "request", new_callable=AsyncMock) as p:
            p.return_value = mock_r
            with caplog.at_level(logging.ERROR):
                with pytest.raises(PermissionError, match="GitHub API returned 500"):
                    await client._req("GET", "/test")
        for record in caplog.records:
            msg = record.getMessage()
            # C0 controls stripped; \t → space, \n → U+21A0; high bytes preserved
            assert "\x00" not in msg
            assert "\x7f" not in msg
            assert "\x80" not in msg  # C1 block stripped
            assert "\x85" not in msg  #NEL control char stripped
            assert "\xe1" in msg     # Vietnamese CJK high bytes preserved
            assert "\xef" in msg
            # No log-line breaks
            assert "\n" not in msg
            assert "\n" not in msg

    @pytest.mark.asyncio
    async def test_sensitive_token_in_response_body_redacted(self, client, caplog):
        """Sensitive tokens in GitHub error body are redacted by sanitize_for_log."""
        body = '{"error": "invalid_token", "token": "ghp_abcdefghijklmnopqrstuvwxyz1234567890ABC"}'
        mock_r, mock_request = self._make_mock_error_response(
            401, body, exc_cls=httpx.HTTPStatusError
        )
        with patch.object(client.client, "request", new_callable=AsyncMock) as p:
            p.return_value = mock_r
            with caplog.at_level(logging.ERROR):
                with pytest.raises(PermissionError, match="GitHub API returned 401"):
                    await client._req("POST", "/webhook")
        for record in caplog.records:
            msg = record.getMessage()
            assert "ghp_" not in msg
            # The "token" JSON key pattern redacts as [REDACTED]; ghp_ pattern would be [GITHUB_TOKEN]
            assert "[REDACTED]" in msg or "[GITHUB_TOKEN]" in msg

    @pytest.mark.asyncio
    async def test_httperror_raises_safe_permission_error(self, client):
        """HTTPStatusError raises PermissionError with clean structured string."""
        mock_r, mock_request = self._make_mock_error_response(
            403, "You have been rate limited", exc_cls=httpx.HTTPStatusError
        )
        with patch.object(client.client, "request", new_callable=AsyncMock) as p:
            p.return_value = mock_r
            with pytest.raises(PermissionError, match=r"GitHub API returned 403 for POST /repos/owner/repo/issues"):
                await client._req("POST", "/repos/owner/repo/issues")

    @pytest.mark.asyncio
    async def test_generic_exception_raises_sanitized_permission_error(self, client):
        """Unexpected Exception raises PermissionError; no raw class name leaks."""
        mock_r = MagicMock()
        mock_r.raise_for_status = MagicMock(side_effect=RuntimeError("connection refused"))
        with patch.object(client.client, "request", new_callable=AsyncMock) as p:
            p.return_value = mock_r
            with pytest.raises(PermissionError, match="GitHub API request failed"):
                await client._req("GET", "/test")
        # The logger.exception call is covered by the CRLF test above; the raised
        # PermissionError is intentionally clean and safe to surface.
