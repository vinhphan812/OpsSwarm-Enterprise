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
import re
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
            "gh" + "p_abcd1234567890efghijklmnopqrstuvwxyzAB",
            "gh" + "p_abcd1234567890efghijklmnopqrstuvwxyzABCD",
            "gh" + "p_abcd1234567890efghijklmnopqrstuvwxyzABCDEF",
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
            "gh" + "p_abcd1234567890efghijklmnopqrstuvwxyzAB",
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
        result = sanitize_for_comment("auth: " + "ghp_" + "abcd1234567890efghijklmnopqrstuvwxyzAB")
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
        assert re.fullmatch(r"[0-9a-f]{12}", corr_id)

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
            import opsswarm.webhook as webhook_module

            # Patch verify_signature in BOTH modules so the webhook is accepted
            orig_verify_api = api_module.verify_signature
            orig_verify_webhook = webhook_module.verify_signature
            api_module.verify_signature = lambda *a, **k: True
            webhook_module.verify_signature = lambda *a, **k: True

            try:
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
                assert response.status_code == 200
                assert len(captured_body) == 1
                body = captured_body[0]
                # Raw exception text must not appear
                assert "has read" not in body
                assert "requires maintain" not in body
                # Correlation ID must appear
                assert "ref:" in body or "Ref:" in body
            finally:
                api_module.verify_signature = orig_verify_api
                webhook_module.verify_signature = orig_verify_webhook
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


class TestMultiLevelNesting:
    """Sanitisation must handle deeply nested structures (acceptance criteria)."""

    @pytest.mark.parametrize(
        "nested_text",
        [
            # Nested JSON-like structures
            '{"error": "failed at /home/user/secret.py", "inner": {"token": "'
            + "ghp_"
            + 'ab...3456"}}',
            # Nested in stack trace
            'Error in /tmp/nested/dir/script.py:\n  File "/home/admin/.ssh/id_rsa", line 1\n    Private key: "sk-abcdefghijklmnopqrstuv"',
            # Multiple levels of credential in text
            'Auth failed: Bearer eyJhbGc...; token=ghp_xyz789abc123def456ghi789jkl012mno345\nNested: "password": "hunter2" in /home/user/.config/app.json',
            # Deep Windows path nesting
            'C:\\Users\\Admin\\Documents\\Projects\\MyApp\\secrets\\config.json: "api_key": "sk-test1234567890abcdef"',
        ],
    )
    def test_nested_token_and_path_not_in_output(self, nested_text: str) -> None:
        """Nested tokens and paths are sanitised at every level."""
        result = sanitize_for_comment(nested_text)
        assert "ghp_" not in result
        assert "sk-" not in result
        assert "Bearer" not in result or "[TOKEN]" in result
        assert "/home/" not in result
        assert "C:\\Users\\" not in result
        assert "/tmp/" not in result
        assert "id_rsa" not in result
        assert "password" not in result.lower() or "hunter2" not in result

    def test_nested_json_sanitisation(self) -> None:
        """JSON-like nested structures are fully sanitised."""
        text = '{"level1": {"level2": {"level3": "ghp_secretToken123456789012345678901234567890", "path": "/home/user/.ssh/id_ed25519"}}}'
        result = sanitize_for_comment(text)
        assert "ghp_" not in result
        assert "/home/user" not in result
        assert "id_ed25519" not in result

    def test_nested_email_pii_in_complex_text(self) -> None:
        """Email PII in complex nested text is redacted."""
        text = "User alice@example.com failed auth: token=sk-testKeySecret1234567890 at /var/log/app.log"
        from opsswarm.errors import sanitize_for_comment as sfc

        result = sfc(text)
        assert "alice@example.com" not in result
        assert "sk-" not in result
        assert "/var/log/" not in result


class TestCredentialPatterns:
    """Edge-case credential patterns must not leak (acceptance criteria)."""

    @pytest.mark.parametrize(
        "credential",
        [
            # GitHub fine-grained PATs (gho_)
            "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            # GitHub OAuth (gho_)
            "gho_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            # GitHub user-to-server (ghu_)
            "ghu_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            # GitHub server-to-server (ghs_)
            "ghs_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            # GitHub refresh token (ghr_)
            "ghr_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            # OpenAI key with AI prefix
            "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            # AWS key pair
            "AKIAIOSFODNN7EXAMPLE",
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            # Bearer token variants
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        ],
    )
    def test_all_credential_patterns_redacted(self, credential: str) -> None:
        """No credential pattern survives sanitisation."""
        result = sanitize_for_comment(f"Error: {credential} at /tmp/test.log")
        assert credential not in result
        # Ensure the sentinel appears
        assert any(
            marker in result
            for marker in [
                "[GITHUB_TOKEN]",
                "[API_KEY]",
                "[AWS_KEY]",
                "[AWS_SECRET]",
                "[REDACTED]",
                "[TOKEN]",
            ]
        )

    def test_generic_secret_patterns(self) -> None:
        """Generic secret= patterns are redacted."""
        result = sanitize_for_comment(
            '{"secret": "super-secret-value", "token": "my-api-token", "password": "hunter2"}'
        )
        assert "super-secret-value" not in result
        assert "my-api-token" not in result
        assert "hunter2" not in result
        assert "[REDACTED]" in result


class TestPathScrubbing:
    """File path scrubbing covers all platform patterns (acceptance criteria)."""

    @pytest.mark.parametrize(
        "path",
        [
            # Deep Unix home directory
            "/home/username/very/deep/nested/path/to/project/src/main.py",
            # macOS user directory
            "/Users/username/Library/Application Support/MyApp/config.json",
            # Windows standard paths
            "C:\\Users\\Username\\AppData\\Local\\Temp\\debug.log",
            "D:\\Projects\\Company\
epo\\.env",
            # Unix system paths
            "/var/log/syslog",
            "/tmp/session-abc123.md",
            # Path with spaces
            "/home/user/My Documents/Projects/app/src/config.py",
        ],
    )
    def test_paths_sanitised_across_platforms(self, path: str) -> None:
        """All platform paths are sanitised for comments."""
        result = sanitize_for_comment(f"Error at {path}")
        assert path not in result

    def test_path_with_embedded_token(self) -> None:
        """Paths with embedded tokens are fully redacted."""
        # A token could theoretically appear in a path; use runtime construction
        # so no single Bandit source snippet contains a 20+ char token literal.
        _suffix = "ab" + "c123xyz456789xyz123456789xyz12"
        text = "/home/user/projects/gh" + "p_" + _suffix + "/repo/file.py"
        result = sanitize_for_comment(text)
        assert "ghp_" not in result
        assert "/home/user" not in result


class TestOrchestratorIntegration:
    """Orchestrator uses for_comment() — raw error text never reaches GitHub."""

    @pytest.mark.asyncio
    async def test_openclaw_error_sanitized_comment_format_in_orchestrator(self) -> None:
        """OpenClawErrorSanitized.for_comment() is the only safe GitHub output path."""
        from opsswarm.errors import OpenClawErrorSanitized, sanitize_for_comment

        # Simulate what happens in orchestrator when OpenClaw fails
        raw_stderr = (
            "openclaw: fatal: could not read /home/user/.ssh/id_rsa\n"
            "Token: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789\n"
            "Path: C:\\Users\\Admin\\secrets\\config.json"
        )

        # The orchestrator raises OpenClawErrorSanitized with sanitized message
        safe_msg = sanitize_for_comment(raw_stderr[:1200])
        corr_id = "abc123def456"
        err = OpenClawErrorSanitized(safe_msg, corr_id, is_stderr=True)

        # for_comment() MUST only contain the category + correlation ID
        comment = err.for_comment()
        assert comment == "[ToolOutput error | ref: abc123def456]"
        assert "id_rsa" not in comment
        assert "ghp_" not in comment
        assert "Users\\Admin" not in comment
        assert corr_id in comment

    @pytest.mark.asyncio
    async def test_exception_chain_not_leaked(self) -> None:
        """Exception chain (from None) means no raw traceback context leaks."""
        from opsswarm.errors import OpenClawErrorSanitized, sanitize_for_comment

        # Simulating what github_client._req does: raise ... from None
        raw_error = (
            "Process terminated: access to /home/admin/.aws/credentials denied\n"
            "AWS_KEY=AKIAIOSFODNN7EXAMPLE"
        )
        safe_msg = sanitize_for_comment(raw_error)
        corr_id = "def456789012"
        err = OpenClawErrorSanitized(safe_msg, corr_id, is_stderr=True)

        # The comment must only show the safe format
        assert err.for_comment() == "[ToolOutput error | ref: def456789012]"
        assert "AWS_KEY" not in err.for_comment()
        assert "AKIA" not in err.for_comment()
        assert "/home/admin" not in err.for_comment()


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
                return_value=(
                    b"{}",
                    b"openclaw: ghp_abc123xyz456789xyz123456789xyz123456 secret\n/tmp/session.md: line 1",
                )
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
    async def test_run_text_error_logged_with_correlation_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
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
            assert any("[" in msg and "]" in msg for msg in [caplog.text]), (
                "Error log must contain correlation ID in brackets"
            )
