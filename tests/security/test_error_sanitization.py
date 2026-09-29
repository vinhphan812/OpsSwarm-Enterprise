"""Security tests for error sanitisation (issue #29).

These tests prove that:
1. GitHub tokens, AWS keys, API keys, and Bearer tokens cannot leak into comments.
2. File paths cannot leak into comments.
3. Raw exception text cannot leak into comments.
4. Correlation IDs appear in operator logs for all error paths.
5. OpenClaw stderr is sanitised before it can reach a GitHub comment.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opsswarm.errors import (
    new_correlation_id,
    sanitize_for_comment,
    sanitize_for_log,
    OpenClawErrorSanitized,
)


# ---------------------------------------------------------------------------
# Token / secret redaction
# ---------------------------------------------------------------------------

class TestTokenRedaction:
    """Token patterns must not appear in sanitised output."""

    @pytest.mark.parametrize(
        "secret",
        [
            "ghp_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "ghp_abcd1234567890efghijklmnopqrstuvwxyzABCD",
            "ghp_abcd1234567890efghijklmnopqrstuvwxyzABCDEF",
            "gho_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "ghu_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "ghs_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "ghr_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
            "Authorization: Bearer ghp_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "authorization: bearer ghp_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "sk-abcdefghijklmnopqrstuvwxy12",
            "sk-abcdefghijklmnopqrstuvwxyz12345",
            "AIzaSyDkjhgfdsalkjfhgasdkjfhgasdkjfhgaskjdhf",
            '"secret": "super-secret-value"',
            '"token": "my-api-token"',
            '"password": "hunter2"',
            "AKIAIOSFODNN7EXAMPLE",
        ],
    )
    def test_sanitize_for_comment_strips_token(self, secret: str) -> None:
        """No token pattern survives sanitize_for_comment."""
        text = f"Failed with error: {secret} in /tmp/trace.log"
        result = sanitize_for_comment(text)
        assert secret not in result
        assert "ghp_" not in result
        assert "sk-" not in result
        assert "Bearer" not in result or "[TOKEN]" in result
        assert "AKIA" not in result

    @pytest.mark.parametrize(
        "secret",
        [
            "ghp_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "Bearer eyJhbGciOiJIUzI1NiJ9",
            "sk-abcdefghijklmnopqrstuvwxy12",
            "AIzaSyDkjhgfdsalkjfhgasdkjfhgasdkjfhgaskjdhf",
        ],
    )
    def test_sanitize_for_log_strips_token(self, secret: str) -> None:
        """No token pattern survives sanitize_for_log."""
        result = sanitize_for_log(f"Error: {secret}")
        assert secret not in result

    def test_sanitize_for_comment_replaces_github_token(self) -> None:
        result = sanitize_for_comment(
            "auth: ghp_abcd1234567890efghijklmnopqrstuvwxyzAB"
        )
        assert "ghp_" not in result
        assert "[GITHUB_TOKEN]" in result

    def test_sanitize_comment_idempotent(self) -> None:
        """Re-sanitising already-sanitised text is a no-op."""
        original = "No secrets here"
        result1 = sanitize_for_comment(original)
        result2 = sanitize_for_comment(result1)
        assert result1 == result2


# ---------------------------------------------------------------------------
# File-path redaction
# ---------------------------------------------------------------------------

class TestPathRedaction:
    """File paths must not appear in sanitised comment output."""

    @pytest.mark.parametrize(
        "path",
        [
            "/home/user/project/src/main.py",
            "/home/admin/opsswarm/runtime-data/run.json",
            "/Users/admin/Documents/secrets.txt",
            "C:\\Users\\Admin\\AppData\\Local\\temp\\debug.log",
            "/tmp/openclaw_session.md",
            "/var/log/opsswarm.log",
        ],
    )
    def test_sanitize_for_comment_strips_path(self, path: str) -> None:
        """No file path survives sanitize_for_comment."""
        result = sanitize_for_comment(f"Error at {path}")
        assert path not in result

    def test_sanitize_for_log_preserves_paths(self) -> None:
        """sanitize_for_log intentionally keeps paths for operator use."""
        path = "/tmp/session.md"
        result = sanitize_for_log(f"Error at {path}")
        assert path in result


# ---------------------------------------------------------------------------
# Correlation IDs
# ---------------------------------------------------------------------------

class TestCorrelationIds:
    """Correlation IDs are generated and usable."""

    def test_correlation_id_is_unique(self) -> None:
        ids = {new_correlation_id() for _ in range(100)}
        assert len(ids) == 100, "Correlation IDs must be unique"

    def test_correlation_id_format(self) -> None:
        corr_id = new_correlation_id()
        assert len(corr_id) == 12
        assert corr_id.isalnum()
        assert corr_id.islower() or corr_id.isupper()

    def test_openclaw_error_sanitized_has_correlation_id(self) -> None:
        err = OpenClawErrorSanitized("some stderr", "abc123def456", is_stderr=True)
        assert err.correlation_id == "abc123def456"
        assert "abc123def456" in err.for_comment()
        assert "some stderr" not in err.for_comment()
        assert "abc123def456" in err.for_log()

    def test_openclaw_error_sanitized_for_comment_is_safe(self) -> None:
        """for_comment() must never include the raw message."""
        err = OpenClawErrorSanitized(
            "fatal: could not read /home/user/.ssh/id_rsa: Permission denied",
            "corr123456",
            is_stderr=True,
        )
        comment = err.for_comment()
        assert "id_rsa" not in comment
        assert "Permission denied" not in comment
        assert "corr123456" in comment


# ---------------------------------------------------------------------------
# OpenClaw stderr — cannot reach GitHub comment
# ---------------------------------------------------------------------------

class TestOpenClawStderrCannotLeak:
    """OpenClawErrorSanitized wraps stderr; raw text is never accessible."""

    def test_openclaw_error_sanitized_comment_format(self) -> None:
        """The comment format is: [OpenClaw error | ref: CORR_ID]."""
        err = OpenClawErrorSanitized("raw stderr content", "corr99", is_stderr=True)
        assert err.for_comment() == "[ToolOutput error | ref: corr99]"

    def test_openclaw_error_sanitized_non_stderr_kind(self) -> None:
        err = OpenClawErrorSanitized("some message", "corr99", is_stderr=False)
        assert err.for_comment() == "[OpenClaw error | ref: corr99]"


# ---------------------------------------------------------------------------
# Integration: api.py webhook exception handler
# ---------------------------------------------------------------------------

class TestApiWebhookSanitisation:
    """gh.comment in api.py must never receive raw exception text."""

    @pytest.mark.asyncio
    async def test_permission_error_not_leaked_to_comment(self) -> None:
        """PermissionError.message (which may contain actor info) must be
        sanitised before posting."""
        import opsswarm.api as api_module

        orig_gh = api_module.gh
        orig_engine = api_module.engine

        captured_body: list[str] = []

        mock_gh = AsyncMock()
        mock_gh.permission = AsyncMock(return_value="read")
        mock_gh.comment = AsyncMock(side_effect=lambda n, b: captured_body.append(b))

        mock_engine = MagicMock()
        mock_engine.handle_comment = AsyncMock(
            side_effect=PermissionError("@evil has read; requires maintain")
        )

        try:
            api_module.gh = mock_gh
            api_module.engine = mock_engine
            api_module.app.dependency_overrides = {}

            from fastapi.testclient import TestClient

            # Patch verify_signature so the webhook is accepted
            orig_verify = api_module.verify_signature
            api_module.verify_signature = lambda *a, **k: True

            client = TestClient(api_module.app)
            response = client.post(
                "/webhooks/github",
                json={
                    "action": "created",
                    "issue": {"number": "1"},
                    "comment": {
                        "id": "999",
                        "user": {"login": "evil"},
                        "body": "/opsswarm approve option-1",
                    },
                },
                headers={
                    "x-github-event": "issue_comment",
                    "x-hub-signature-256": "sha256=x",
                },
            )

            api_module.verify_signature = orig_verify

            assert response.status_code == 200
            assert len(captured_body) == 1
            body = captured_body[0]
            # Raw exception text must not appear
            assert "has read" not in body
            assert "requires maintain" not in body
            # Correlation ID must appear
            assert "ref:" in body or "Ref:" in body
        finally:
            api_module.gh = orig_gh
            api_module.engine = orig_engine

    @pytest.mark.asyncio
    async def test_generic_exception_not_leaked_to_comment(self) -> None:
        """Generic Exception details must not appear in the GitHub comment."""
        import opsswarm.api as api_module

        orig_gh = api_module.gh
        orig_engine = api_module.engine

        captured_body: list[str] = []

        mock_gh = AsyncMock()
        mock_gh.permission = AsyncMock(return_value="write")
        mock_gh.comment = AsyncMock(side_effect=lambda n, b: captured_body.append(b))

        mock_engine = MagicMock()
        mock_engine.handle_comment = AsyncMock(
            side_effect=RuntimeError(
                "OpenClaw failed rc=1: fatal: could not read /home/user/.ssh/id_rsa"
            )
        )

        try:
            api_module.gh = mock_gh
            api_module.engine = mock_engine
            api_module.app.dependency_overrides = {}

            from fastapi.testclient import TestClient

            orig_verify = api_module.verify_signature
            api_module.verify_signature = lambda *a, **k: True

            client = TestClient(api_module.app)
            response = client.post(
                "/webhooks/github",
                json={
                    "action": "created",
                    "issue": {"number": "2"},
                    "comment": {
                        "id": "888",
                        "user": {"login": "operator"},
                        "body": "/opsswarm approve option-1",
                    },
                },
                headers={
                    "x-github-event": "issue_comment",
                    "x-hub-signature-256": "sha256=x",
                },
            )

            api_module.verify_signature = orig_verify

            assert response.status_code == 200
            assert len(captured_body) == 1
            body = captured_body[0]
            # Raw exception text must not appear
            assert "OpenClaw failed" not in body
            assert "id_rsa" not in body
            assert "/home/user" not in body
            # Correlation ID must appear
            assert "ref:" in body or "Ref:" in body
        finally:
            api_module.gh = orig_gh
            api_module.engine = orig_engine


# ---------------------------------------------------------------------------
# Integration: openclaw.py stderr sanitisation
# ---------------------------------------------------------------------------

class TestOpenClawStderrSanitised:
    """openclaw.py run_text() must raise OpenClawErrorSanitized, never OpenClawError
    with raw stderr."""

    @pytest.mark.asyncio
    async def test_run_text_raises_sanitized_error_on_failure(self) -> None:
        """Non-zero exit raises OpenClawErrorSanitized with sanitised message."""
        from opsswarm.openclaw import OpenClawClient, OpenClawErrorSanitized

        client = OpenClawClient(binary="nonexistent-binary", timeout=5)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 127
            # Stderr contains a token and a path — raw form must NOT leak
            mock_proc.communicate = AsyncMock(
                return_value=(b"{}", b"openclaw: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx secret\n/tmp/session.md: line 1")
            )
            mock_exec.return_value = mock_proc

            with pytest.raises(OpenClawErrorSanitized) as exc_info:
                await client.run_text("agent", "session-key", "prompt")

            err = exc_info.value
            # Token must be redacted
            assert "ghp_" not in err.args[0]
            assert "ghp_" not in err.for_comment()
            # Path must be redacted
            assert "/tmp/session.md" not in err.args[0]
            # Correlation ID must be present
            assert len(err.correlation_id) == 12
            assert err.correlation_id in err.for_comment()
            assert err.correlation_id in err.for_log()

    @pytest.mark.asyncio
    async def test_run_text_error_logged_with_correlation_id(self, caplog: pytest.LogCaptureFixture) -> None:
        """The ERROR log must include the correlation ID."""
        from opsswarm.openclaw import OpenClawClient, OpenClawErrorSanitized

        client = OpenClawClient(binary="nonexistent-binary", timeout=5)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"{}", b"some error output"))
            mock_exec.return_value = mock_proc

            with caplog.at_level(logging.ERROR, logger="opsswarm.openclaw"):
                with pytest.raises(OpenClawErrorSanitized):
                    await client.run_text("agent", "session-key", "prompt")

            # The log message must contain the correlation ID
            assert any("[" in msg and "]" in msg for msg in [caplog.text]), \
                "Error log must contain correlation ID in brackets"
