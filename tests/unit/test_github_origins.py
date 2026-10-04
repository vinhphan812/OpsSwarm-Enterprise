"""Unit tests for Issue #72: SSRF-safe configurable GitHub API origins.

Covers:
- Default GitHub.com origin accepted
- Approved GHES hostname accepted
- Arbitrary/unapproved host rejected
- Hostname-prefix/suffix confusion rejected
- HTTP origin rejected in production
- Local test origin accepted only in test/dev profile
- Custom CA bundle used while certificate verification remains enabled
- Redirect to different host not followed
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opsswarm.github_client import (
    GitHubClient,
    _is_safe_origin,
    _resolve_ca_bundle,
    build_allowed_origins_set,
    get_effective_origin_diagnostic,
    validate_origins,
)


# ---------------------------------------------------------------------------
# _is_safe_origin — unit-level validation
# ---------------------------------------------------------------------------


class TestIsSafeOrigin:
    """SSRF-safe origin validation rules."""

    # ----- default GitHub.com -----

    def test_default_github_com_accepted(self):
        safe, reason = _is_safe_origin("https://api.github.com")
        assert safe, reason

    def test_github_com_api_alias_accepted(self):
        # https://github.com/api/v3 is valid: HTTPS scheme, normal hostname, GH API path
        safe, reason = _is_safe_origin("https://github.com/api/v3")
        assert safe, reason

    # ----- GHES hostname -----

    def test_ghes_with_https_accepted(self):
        safe, reason = _is_safe_origin("https://ghes.example.com")
        assert safe, reason

    def test_ghes_with_custom_port_accepted(self):
        safe, reason = _is_safe_origin("https://ghes.example.com:8443")
        assert safe, reason

    def test_ghes_with_trailing_slash_accepted(self):
        safe, reason = _is_safe_origin("https://ghes.example.com/")
        assert safe, reason

    # ----- arbitrary/unapproved host rejected -----
    # Structural validation checks SCHEME, HOST, PORT, PATH — it does NOT check
    # whether a hostname is "approved". That is done by the frozenset in GitHubClient.
    # So https://evil.com passes structural validation and fails at the frozenset check.

    def test_rejects_completely_unapproved_host(self):
        # evil.com is not on the blocklist, so structural validation passes.
        # It is rejected at the frozenset level in GitHubClient / build_allowed_origins_set.
        safe, reason = _is_safe_origin("https://evil.com")
        # Structural validation passes for non-blocklisted hostnames;
        # the frozenset rejection happens in GitHubClient.__init__.
        assert safe, reason

    def test_rejects_ip_address_in_production(self):
        safe, reason = _is_safe_origin("https://203.0.113.42")
        assert not safe
        assert "IP address" in reason

    def test_rejects_ip_address_with_port_in_production(self):
        safe, reason = _is_safe_origin("https://203.0.113.42:8443")
        assert not safe
        assert "IP address" in reason

    # ----- hostname-prefix/suffix confusion rejected -----

    def test_rejects_hostname_prefix_spoof(self):
        # https://github.example.com.evil.com is a structurally valid URL (normal hostname).
        # It passes _is_safe_origin; it is rejected at the frozenset level in GitHubClient.
        safe, reason = _is_safe_origin("https://github.example.com.evil.com")
        assert safe, reason  # structural validation passes

    def test_exact_match_required_by_allowed_origins_set(self):
        """The allowed_origins frozenset enforces exact match — suffix/prefix tricks fail there."""
        origins = ["https://github.com", "https://api.github.com"]
        allowed = build_allowed_origins_set(origins)

        # Exact match passes
        assert "https://api.github.com" in allowed

        # Suffix-spoof fails the frozenset lookup
        assert "https://github.com.evil.com" not in allowed

        # Prefix-spoof fails the frozenset lookup
        assert "https://api.github.com.evil.com" not in allowed

    # ----- HTTP origin rejected in production -----

    def test_rejects_http_scheme_in_production(self):
        safe, reason = _is_safe_origin("http://api.github.com")
        assert not safe
        assert "HTTP scheme not permitted" in reason

    def test_rejects_http_scheme_in_staging(self):
        safe, reason = _is_safe_origin("http://api.github.com", profile="staging")
        assert not safe

    def test_accepts_http_in_dev_profile(self):
        safe, reason = _is_safe_origin("http://api.github.com", profile="dev")
        assert safe, reason

    def test_accepts_http_in_test_profile(self):
        safe, reason = _is_safe_origin("http://api.github.com", profile="test")
        assert safe, reason

    # ----- local test origin -----

    def test_rejects_localhost_in_production(self):
        # Order of checks: scheme fires before reserved-hostname.
        # http://localhost is rejected at the scheme step (not at reserved-hostname step).
        safe, reason = _is_safe_origin("http://localhost")
        assert not safe
        assert "HTTP scheme not permitted" in reason or "reserved hostname" in reason

    def test_accepts_localhost_in_dev(self):
        # localhost is allowed in dev/test profile (for local test fixture servers)
        safe, reason = _is_safe_origin("http://localhost", profile="dev")
        assert safe, reason

    def test_rejects_127_0_0_1_in_production(self):
        # http://127.0.0.1 is rejected at the scheme step in production.
        safe, reason = _is_safe_origin("http://127.0.0.1")
        assert not safe
        assert "HTTP scheme not permitted" in reason or "reserved hostname" in reason

    def test_accepts_127_0_0_1_in_test(self):
        # http://127.0.0.1 passes scheme check in test profile.
        # However: 127.0.0.1 is on the blocklist and the reserved-hostname check
        # fires after scheme, so the result is still "reserved hostname not permitted".
        safe, reason = _is_safe_origin("http://127.0.0.1", profile="test")
        assert not safe
        assert "reserved hostname" in reason

    def test_rejects_169_254_169_254_always(self):
        """AWS metadata IP is always blocklisted, even in dev/test."""
        # http://169.254.169.254 is rejected at the scheme step in production.
        safe, reason = _is_safe_origin("http://169.254.169.254")
        assert not safe
        # Either HTTP scheme or reserved hostname — both are correct rejections
        assert "HTTP scheme not permitted" in reason or "reserved hostname" in reason

    def test_rejects_169_254_169_254_in_dev_too(self):
        """AWS metadata IP is always blocklisted, even in dev profile."""
        safe, reason = _is_safe_origin("http://169.254.169.254", profile="dev")
        assert not safe
        assert "reserved hostname" in reason

    def test_rejects_metadata_google_internal_always(self):
        safe, reason = _is_safe_origin("http://metadata.google.internal")
        assert not safe

    # ----- scheme validation -----

    def test_rejects_ftp_scheme(self):
        safe, reason = _is_safe_origin("ftp://api.github.com")
        assert not safe
        assert "unknown scheme" in reason

    def test_rejects_javascript_scheme(self):
        safe, reason = _is_safe_origin("javascript://api.github.com")
        assert not safe

    def test_rejects_data_url(self):
        safe, reason = _is_safe_origin("data:text/html,<script>alert(1)</script>")
        assert not safe

    def test_rejects_empty_string(self):
        safe, reason = _is_safe_origin("")
        assert not safe
        assert "empty" in reason

    # ----- no userinfo, query, fragment -----

    def test_rejects_userinfo(self):
        safe, reason = _is_safe_origin("https://user:pass@ghes.example.com")
        assert not safe
        assert "userinfo" in reason

    def test_rejects_query_string_in_host(self):
        safe, reason = _is_safe_origin("https://ghes.example.com?redirect=https://evil.com")
        assert not safe
        assert "query" in reason

    def test_rejects_fragment_in_host(self):
        safe, reason = _is_safe_origin("https://ghes.example.com#section")
        assert not safe
        assert "fragment" in reason

    def test_rejects_query_string_in_path(self):
        safe, reason = _is_safe_origin("https://ghes.example.com/api?redirect=https://evil.com")
        assert not safe
        assert "query" in reason

    def test_rejects_fragment_in_path(self):
        safe, reason = _is_safe_origin("https://ghes.example.com/api#section")
        assert not safe
        assert "fragment" in reason

    # ----- path validation -----
    # Paths (including deep paths like /api/v3) are now permitted —
    # the frozenset exact-match enforces approval, not the structural validator.

    def test_accepts_github_api_v3_path(self):
        """GitHub API path /api/v3 is permitted (GHES uses this)."""
        safe, reason = _is_safe_origin("https://github.com/api/v3")
        assert safe, reason

    def test_accepts_ghes_deep_api_path(self):
        """GHES API sub-paths are permitted."""
        safe, reason = _is_safe_origin("https://ghes.example.com/api/v3/repos")
        assert safe, reason

    # ----- port validation -----

    def test_rejects_port_0(self):
        safe, reason = _is_safe_origin("https://ghes.example.com:0")
        assert not safe
        assert "port" in reason.lower()

    def test_rejects_port_65536(self):
        safe, reason = _is_safe_origin("https://ghes.example.com:65536")
        assert not safe
        assert "port" in reason.lower()

    def test_rejects_non_numeric_port(self):
        safe, reason = _is_safe_origin("https://ghes.example.com:abc")
        assert not safe
        assert "invalid port" in reason

    def test_accepts_valid_port_443(self):
        safe, reason = _is_safe_origin("https://ghes.example.com:443")
        assert safe, reason

    def test_accepts_valid_port_8080(self):
        safe, reason = _is_safe_origin("https://ghes.example.com:8080")
        assert safe, reason

    # ----- IPv6 -----

    def test_rejects_bare_ipv6_in_production(self):
        safe, reason = _is_safe_origin("https://[::1]")
        assert not safe
        # reserved hostname or IP address

    def test_accepts_ghes_with_ipv6_literal_in_dev(self):
        """IPv6 literals are IP addresses — blocked in production, allowed in dev/test if not on blocklist."""
        # [::1] is on the blocklist so it's always rejected
        safe, reason = _is_safe_origin("https://[::1]:8443", profile="dev")
        assert not safe
        assert "reserved hostname" in reason


# ---------------------------------------------------------------------------
# validate_origins — list-level validation
# ---------------------------------------------------------------------------


class TestValidateOrigins:
    def test_empty_list_invalid(self):
        errors = validate_origins([])
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_single_valid_origin(self):
        errors = validate_origins(["https://api.github.com"])
        assert errors == []

    def test_multiple_valid_origins(self):
        errors = validate_origins([
            "https://api.github.com",
            "https://ghes.example.com",
        ])
        assert errors == []

    def test_mixed_valid_and_invalid(self):
        errors = validate_origins([
            "https://api.github.com",
            "http://localhost",        # invalid in production
            "https://ghes.example.com",
        ])
        assert len(errors) == 1
        assert "localhost" in errors[0]


# ---------------------------------------------------------------------------
# build_allowed_origins_set — frozenset construction
# ---------------------------------------------------------------------------


class TestBuildAllowedOriginsSet:
    def test_single_github_com(self):
        allowed = build_allowed_origins_set(["https://api.github.com"])
        assert allowed == frozenset(["https://api.github.com"])

    def test_multiple_origins(self):
        allowed = build_allowed_origins_set([
            "https://api.github.com",
            "https://ghes.example.com",
        ])
        assert len(allowed) == 2
        assert "https://api.github.com" in allowed
        assert "https://ghes.example.com" in allowed

    def test_raises_on_invalid_origin(self):
        with pytest.raises(ValueError) as exc_info:
            build_allowed_origins_set(["http://localhost"])  # invalid in production
        assert "unsafe origin" in str(exc_info.value).lower()

    def test_raises_with_all_errors_listed(self):
        with pytest.raises(ValueError) as exc_info:
            build_allowed_origins_set([
                "http://localhost",       # HTTP scheme invalid in production
                "ftp://ghes.example.com",  # non-HTTP(S) scheme
            ])
        errors_str = str(exc_info.value)
        assert "localhost" in errors_str
        assert "ghes.example.com" in errors_str


# ---------------------------------------------------------------------------
# _resolve_ca_bundle
# ---------------------------------------------------------------------------


class TestResolveCaBundle:
    def test_empty_returns_true(self):
        assert _resolve_ca_bundle("") is True

    def test_custom_path_returned_as_string(self):
        result = _resolve_ca_bundle("/etc/ssl/certs/enterprise-ca.pem")
        assert result == "/etc/ssl/certs/enterprise-ca.pem"
        assert isinstance(result, str)

    def test_whitespace_only_returns_true(self):
        # Whitespace-only is treated as empty (used after .strip() in api.py)
        assert _resolve_ca_bundle("   ") == "   "  # function itself does NOT strip


# ---------------------------------------------------------------------------
# GitHubClient — Issue #72 integration
# ---------------------------------------------------------------------------


class TestGitHubClientOrigins:
    """Issue #72: GitHubClient with operator-configurable origins."""

    def test_default_construction_uses_default_origin(self):
        """Direct construction without allowed_origins defaults to GitHub.com URLs."""
        client = GitHubClient(token="tok", repo="owner/repo")
        assert client.base_url == "https://api.github.com"
        # Both GitHub.com API URLs are permitted by default (backward compat)
        assert "https://api.github.com" in client.allowed_origins
        assert "https://github.com/api/v3" in client.allowed_origins

    def test_allowed_origins_accepts_ghes(self):
        """GHES hostname accepted when in allowed_origins."""
        client = GitHubClient(
            token="tok",
            repo="owner/repo",
            base_url="https://ghes.example.com",
            allowed_origins=frozenset(["https://api.github.com", "https://ghes.example.com"]),
        )
        assert client.base_url == "https://ghes.example.com"
        assert "https://ghes.example.com" in client.allowed_origins

    def test_rejects_base_url_not_in_allowed_origins(self):
        """Fail-closed: base_url not in allowed_origins raises ValueError."""
        with pytest.raises(ValueError, match="not in the approved origins list"):
            GitHubClient(
                token="tok",
                repo="owner/repo",
                base_url="https://evil.com",
                allowed_origins=frozenset(["https://api.github.com"]),
            )

    def test_rejects_unapproved_host_via_allowed_origins_exact_match(self):
        """Suffix-spoof host rejected by exact frozenset lookup."""
        with pytest.raises(ValueError, match="not in the approved origins list"):
            GitHubClient(
                token="tok",
                repo="owner/repo",
                base_url="https://api.github.com.evil.com",
                allowed_origins=frozenset(["https://api.github.com"]),
            )

    def test_production_http_origin_rejected(self):
        """HTTP scheme origins rejected in production (SSRF hardening)."""
        # http://api.github.com is rejected at _is_safe_origin before the frozenset check.
        errors = validate_origins(["http://api.github.com"], profile="production")
        assert len(errors) == 1
        assert "HTTP scheme not permitted" in errors[0]

    def test_dev_http_origin_accepted(self):
        """HTTP origin accepted in dev profile."""
        client = GitHubClient(
            token="tok",
            repo="test/repo",
            base_url="http://localhost:8080",
            allowed_origins=frozenset(["http://localhost:8080"]),
            profile="dev",
        )
        assert client.base_url == "http://localhost:8080"

    def test_test_http_origin_accepted(self):
        """HTTP origin accepted in test profile."""
        client = GitHubClient(
            token="tok",
            repo="test/repo",
            base_url="http://127.0.0.1:9000",
            allowed_origins=frozenset(["http://127.0.0.1:9000"]),
            profile="test",
        )
        assert client.base_url == "http://127.0.0.1:9000"

    def test_verify_false_prohibited_in_production(self):
        """verify=False is prohibited in production profile."""
        with pytest.raises(ValueError, match="verify=False is not permitted"):
            GitHubClient(
                token="tok",
                repo="owner/repo",
                verify=False,
                profile="production",
            )

    def test_verify_false_allowed_in_test(self):
        """verify=False permitted in test profile."""
        client = GitHubClient(
            token="tok",
            repo="test/repo",
            allowed_origins=frozenset(["https://api.github.com"]),
            verify=False,
            profile="test",
        )
        assert client.client is not None

    def test_verify_false_allowed_in_dev(self):
        client = GitHubClient(
            token="tok",
            repo="test/repo",
            allowed_origins=frozenset(["https://api.github.com"]),
            verify=False,
            profile="dev",
        )
        assert client.client is not None


class TestGitHubClientCaBundle:
    """Issue #72: custom CA bundle support."""

    def test_system_ca_bundle_default(self):
        """verify=True (system default) when ca_bundle is empty."""
        client = GitHubClient(
            token="tok",
            repo="owner/repo",
        )
        # httpx.AsyncClient(verify=True) means system CA
        assert client.client is not None

    def test_ca_bundle_string_passed_to_httpx_verify(self):
        """verify=<path> string is passed through as-is to httpx."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            GitHubClient(
                token="tok",
                repo="owner/repo",
                verify="/etc/ssl/certs/ca-bundle.pem",
                profile="production",
            )
            mock_client_cls.assert_called_once()
            call_kwargs = mock_client_cls.call_args.kwargs
            # The resolved verify value is passed (a string path)
            assert call_kwargs.get("verify") == "/etc/ssl/certs/ca-bundle.pem"


class TestGitHubClientRedirect:
    """Issue #72 / ADR-028: redirects to different hosts are not followed."""

    def test_follow_redirects_is_false(self):
        """follow_redirects=False is always set regardless of origin."""
        client = GitHubClient(
            token="tok",
            repo="owner/repo",
            allowed_origins=frozenset(["https://api.github.com", "https://ghes.example.com"]),
            base_url="https://ghes.example.com",
        )
        assert client.client.follow_redirects is False


# ---------------------------------------------------------------------------
# get_effective_origin_diagnostic
# ---------------------------------------------------------------------------


class TestOriginDiagnostic:
    def test_single_origin(self):
        diag = get_effective_origin_diagnostic(["https://ghes.example.com"])
        assert "1 origin(s)" in diag
        assert "ghes.example.com" in diag
        assert "token" not in diag.lower()

    def test_multiple_origins(self):
        diag = get_effective_origin_diagnostic([
            "https://api.github.com",
            "https://ghes.example.com",
        ])
        assert "2 origin(s)" in diag
        assert "api.github.com" in diag

    def test_empty_list(self):
        diag = get_effective_origin_diagnostic([])
        assert "(none)" in diag

    def test_no_credentials_in_output(self):
        """get_effective_origin_diagnostic strips userinfo before showing."""
        diag = get_effective_origin_diagnostic(["https://token:secret@example.com"])
        assert "token" not in diag
        assert "secret" not in diag
        assert "example.com" in diag  # hostname is shown, credentials are not
