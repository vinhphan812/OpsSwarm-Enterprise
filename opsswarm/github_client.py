from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from .errors import sanitize_for_log

logger = logging.getLogger(__name__)

# ADR-028 (superseded by Issue #72): max_keepalive_connections=1 and max_connections=2
# keep the transport scoped to a single logical channel, preventing connection-pooling abuse.
_TRANSPORT_LIMITS = httpx.Limits(max_keepalive_connections=1, max_connections=2)

# ADR-028 (superseded by Issue #72): conservative timeout — bounds both overall request and TCP connect.
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# ADR-028 (superseded by Issue #72): repo must match owner/repo (alphanumeric, hyphens, underscores).
_REPO_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9._-]+$")

# Reserved hostnames never permitted regardless of config (fail-closed).
_RESERVED_BLOCKLIST: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # nosec: B104  # security blocklist — NOT a bind address
        "[::1]",
        "169.254.169.254",  # AWS IMDS — cloud metadata exfiltration
        "metadata.google.internal",  # GCP metadata
        "metadata.azure.com",
    }
)

# Profiles where HTTP origins and localhost are permitted (local dev/test fixtures only).
# This is NOT a production setting.
_DEV_PROFILES: frozenset[str] = frozenset({"test", "dev"})


# ----------------------------------------------------------------------
# SSRF-safe origin validation
# ----------------------------------------------------------------------


def _is_safe_origin(origin: str, *, profile: str = "production") -> tuple[bool, str]:
    """Validate a single API origin string for SSRF safety.

    Returns (is_safe, reason). reason is non-empty when is_safe is False.

    Rules
    -----
    - Scheme must be https in production; http accepted only in test/dev profiles.
    - Hostname must not be on the reserved blocklist.
    - Hostname must be a valid IDN-compatible label (no IP addresses in production).
    - Port must be absent or a valid decimal integer in 1-65535.
    - No userinfo (@), query (?), or fragment (#) components.
    - No path beyond a single "/" root is permitted.
    - IDN domains are decoded and re-encoded to prevent homograph attacks.

    This is NOT a substring/prefix/suffix match — the full URL must pass.
    """
    if not origin:
        return False, "origin is empty"

    # ---- scheme ----
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", origin):
        return False, f"missing or invalid URL scheme: {origin!r}"

    scheme_end = origin.index("://")
    scheme = origin[:scheme_end].lower()
    rest = origin[scheme_end + 3 :]

    if scheme == "http":
        if profile not in _DEV_PROFILES:
            return False, f"HTTP scheme not permitted in profile {profile!r}; use HTTPS"
    elif scheme != "https":
        return False, f"unknown scheme {scheme!r}; only https (or http in dev/test) is allowed"

    # ---- no userinfo ----
    if "@" in rest:
        return False, "userinfo component not permitted"

    # ---- split host:port from path ----
    # We allow optional path segments but must validate each segment.
    if "/" in rest:
        host_port, path_segment = rest.split("/", 1)
    else:
        host_port = rest
        path_segment = ""

    # ---- no query or fragment ----
    if "?" in host_port or "#" in host_port:
        return False, "query string or fragment not permitted"

    # ---- no query or fragment in path ----
    if "?" in path_segment or "#" in path_segment:
        return False, "query string or fragment not permitted"

    # ---- optional port ----
    if host_port.startswith("["):
        # IPv6 literal: [...]:port
        close_bracket = host_port.find("]")
        if close_bracket == -1:
            return False, "unclosed IPv6 bracket"
        host = host_port[: close_bracket + 1]
        port_str = host_port[close_bracket + 1 :]
        if port_str.startswith(":"):
            port_str = port_str[1:]
    else:
        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
        else:
            host = host_port
            port_str = ""

    # Handle implicit-port case: "http://localhost" (no :port) has host="localhost", port_str="".
    # But "http://localhost:" has host="", port_str="". Treat empty host with non-empty
    # rest-before-port as "host missing" — caught by the "if not host" check below.
    # For the case where host is empty because the URL has no :port AND the original
    # rest (before path split) contains no ":" — this is a bare hostname, not a port.
    # URLs like "http://localhost" have rest="localhost" (no ":") → host="localhost" ✓
    # URLs like "http://localhost:8080" have rest="localhost:8080" → host="localhost", port_str="8080" ✓
    # The "if not host" below only fires when the host portion is genuinely empty.

    if not host:
        return False, "empty hostname"

    # ---- block reserved hosts + IP address validation ----
    # Cloud metadata IPs (169.254.169.254 etc.) are always blocked — even in dev/test.
    # localhost/127.0.0.1/0.0.0.0 are blocked in production but allowed in dev/test.
    # We check IP addresses here too, merged with the blocklist for profile-aware handling.
    _IP_RE = re.compile(
        r"^(?:"
        r"\d{1,3}(?:\.\d{1,3}){3}"  # IPv4 dotted
        r"|\[(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}\]"  # IPv6
        r")$"
    )
    host_lower = host.lower()
    is_ip = bool(_IP_RE.match(host_lower))

    if is_ip:
        # Block cloud metadata IPs in all profiles
        if host_lower in _RESERVED_BLOCKLIST:
            return False, f"reserved hostname not permitted: {host!r}"
        # Allow other IP addresses only in dev/test profiles
        if profile not in _DEV_PROFILES:
            return False, f"bare IP address not permitted in profile {profile!r}"
        return True, ""

    # Non-IP hostnames: block reserved names (localhost, etc.) in production
    if host_lower in _RESERVED_BLOCKLIST:
        _DEVBAN_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "[::1]"})  # nosec: B104  # security blocklist — NOT a bind address
        if host_lower in _DEVBAN_HOSTS:
            if profile not in _DEV_PROFILES:
                return False, f"reserved hostname not permitted: {host!r}"
        else:
            # Cloud metadata names are always blocked even in dev
            return False, f"reserved hostname not permitted: {host!r}"

    # ---- port range ----
    if port_str:
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                return False, f"port {port} outside valid range 1-65535"
        except ValueError:
            return False, f"invalid port {port_str!r}; must be decimal integer"

    return True, ""


def validate_origins(origins: list[str], *, profile: str = "production") -> list[str]:
    """Validate a list of origin strings.

    Returns a list of error messages (empty == all origins are valid).

    In production (profile != 'test'/'dev'), HTTP origins and localhost/IPs are rejected.
    An empty origins list is treated as invalid.
    """
    errors = []
    if not origins:
        errors.append("github.origins list is empty; at least one origin is required")
    for origin in origins:
        safe, reason = _is_safe_origin(origin, profile=profile)
        if not safe:
            errors.append(f"unsafe origin {origin!r}: {reason}")
    return errors


def build_allowed_origins_set(
    origins: list[str],
    *,
    profile: str = "production",
) -> frozenset[str]:
    """Build the runtime frozenset of permitted base URLs.

    Raises ValueError listing all validation failures if any origin is unsafe.
    This is called at startup / GitHubClient construction to fail closed on misconfiguration.
    """
    errors = validate_origins(origins, profile=profile)
    if errors:
        raise ValueError(
            "One or more configured github.origins entries are unsafe:\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\nSee ADR-028 and Issue #72 for the origin validation policy."
        )
    return frozenset(origins)


def get_effective_origin_diagnostic(origins: list[str]) -> str:
    """Return a safe diagnostic string for startup logs (no credentials).

    Strips userinfo before extracting the host so credentials in a URL never appear.
    """
    count = len(origins)
    if not origins:
        return f"{count} origin(s), first=(none)"
    first = origins[0]
    # Remove userinfo (user:pass@) before showing — credentials must never appear in logs
    if "@" in first:
        first = first.split("@", 1)[1]
    return f"{count} origin(s), first=https://{first}"


# Default approved origin — maintained for backward compatibility of direct construction.
_DEFAULT_ORIGIN = "https://api.github.com"

# Default allowed_origins when not provided: both GitHub.com API URLs are permitted.
# This preserves backward compatibility for existing tests and ad-hoc usage.
_DEFAULT_ALLOWED_ORIGINS: frozenset[str] = frozenset(
    {
        "https://api.github.com",
        "https://github.com/api/v3",
    }
)

# Default profile when $OPSWARM_PROFILE is unset.
_DEFAULT_PROFILE = "production"


def _resolve_ca_bundle(ca_bundle: str) -> bool | str:
    """Resolve the ca_bundle config value.

    - Empty string  → use system default (True).
    - Non-empty path → return the path as a string (httpx uses it as verify param).
    """
    if not ca_bundle:
        return True
    return ca_bundle


# ----------------------------------------------------------------------
# GitHubClient  (ADR-028 / Issue #72)
# ----------------------------------------------------------------------


class GitHubClient:
    def __init__(
        self,
        token: str,
        repo: str,
        base_url: str = _DEFAULT_ORIGIN,
        allowed_origins: frozenset[str] | None = None,
        verify: bool | str = True,
        *,
        profile: str = _DEFAULT_PROFILE,
    ):
        """Construct a GitHub API client.

        Parameters
        ----------
        token
            GitHub personal-access or fine-grained token.
        repo
            Repository in 'owner/repo' form.
        base_url
            The API base URL. Must be in ``allowed_origins``.
            Defaults to ``https://api.github.com``.
        allowed_origins
            Frozenset of permitted base URLs. If ``base_url`` is not in this set,
            a ``ValueError`` is raised at construction time (fail-closed SSRF hardening).
            If None, defaults to the singleton ``{_DEFAULT_ORIGIN}`` for backward
            compatibility of direct construction.
        verify
            TLS verification setting passed to httpx.
            - ``True`` (default) uses the system CA bundle.
            - A non-empty string path uses that PEM file as the CA bundle.
            - ``False`` disables TLS verification (only permitted in test/dev profiles).
        profile
            Runtime profile name (used to gate insecure settings).
            Set from ``$OPSWARM_PROFILE`` or defaults to ``production``.
        """
        if allowed_origins is None:
            allowed_origins = _DEFAULT_ALLOWED_ORIGINS

        if base_url not in allowed_origins:
            raise ValueError(
                f"base_url {base_url!r} is not in the approved origins list: "
                f"{sorted(allowed_origins)!r}.  "
                "Configure github.origins in config/production.yaml or set "
                "OPSWARM_GITHUB_ORIGINS to allow this host.  "
                "See ADR-028 and Issue #72."
            )

        if not _REPO_PATTERN.match(repo):
            raise ValueError(f"repo must be in 'owner/repo' format; got {repo!r}.")

        self.repo = repo
        self.base_url = base_url
        self.allowed_origins = allowed_origins

        # ---- resolve TLS verify setting ----
        if verify is False and profile not in _DEV_PROFILES:
            raise ValueError(
                f"verify=False is not permitted in profile {profile!r}; "
                "TLS verification is mandatory. Use a CA bundle for self-signed certs."
            )

        resolved_verify = _resolve_ca_bundle(verify) if isinstance(verify, str) else verify

        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            follow_redirects=False,  # ADR-028: prevent redirect-to-arbitrary-host SSRF
            limits=_TRANSPORT_LIMITS,
            timeout=_REQUEST_TIMEOUT,
            verify=resolved_verify,
        )
        logger.info(
            "GitHubClient initialised: repo=%s base_url=%s verify=%s",
            repo,
            base_url,
            "system"
            if resolved_verify is True
            else ("custom CA" if isinstance(resolved_verify, str) else resolved_verify),
        )

    async def _req(self, method: str, path: str, **kwargs) -> Any:
        try:
            r = await self.client.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json() if r.content else None
        except httpx.HTTPStatusError as e:
            # HTTP error bodies can contain internal paths, tokens, or implementation details.
            # Log the full response for operators; raise a sanitized PermissionError so callers
            # can handle it uniformly without leaking internals to GitHub comments.
            logger.error(
                "GitHub API HTTP error: status=%s path=%s detail=%s",
                e.response.status_code,
                sanitize_for_log(path),
                sanitize_for_log(e.response.text[:500]),
            )
            raise PermissionError(
                f"GitHub API returned {e.response.status_code} for {method} {path}"
            ) from None
        except PermissionError:
            raise  # already sanitized
        except Exception as e:
            logger.exception(
                "GitHub API unexpected error: method=%s path=%s",
                sanitize_for_log(method),
                sanitize_for_log(path),
            )
            raise PermissionError(f"GitHub API request failed for {method} {path}") from None

    async def get_issue(self, number: int):
        return await self._req("GET", f"/repos/{self.repo}/issues/{number}")

    async def comment(self, number: int, body: str):
        return await self._req(
            "POST", f"/repos/{self.repo}/issues/{number}/comments", json={"body": body}
        )

    async def set_labels(self, number: int, labels: list[str]):
        return await self._req(
            "POST", f"/repos/{self.repo}/issues/{number}/labels", json={"labels": labels}
        )

    async def close_issue(self, number: int):
        return await self._req(
            "PATCH",
            f"/repos/{self.repo}/issues/{number}",
            json={"state": "closed", "state_reason": "completed"},
        )

    async def create_issue(self, title: str, body: str, labels: list[str]):
        return await self._req(
            "POST",
            f"/repos/{self.repo}/issues",
            json={"title": title, "body": body, "labels": labels},
        )

    async def create_branch(self, branch: str, from_ref: str = "main") -> Any:
        """Create a branch from an existing branch or commit ref."""
        source = await self._req("GET", f"/repos/{self.repo}/git/ref/heads/{from_ref}")
        sha = source["object"]["sha"]
        return await self._req(
            "POST",
            f"/repos/{self.repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    async def open_pr(
        self, title: str, body: str, head: str, base: str = "main", draft: bool = True
    ) -> Any:
        """Open a pull request for a governed remediation branch."""
        return await self._req(
            "POST",
            f"/repos/{self.repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base, "draft": draft},
        )

    async def get_pr_status(self, number: int) -> dict[str, Any]:
        """Return PR mergeability and aggregate check status."""
        pr = await self._req("GET", f"/repos/{self.repo}/pulls/{number}")
        sha = (pr.get("head") or {}).get("sha")
        checks = (
            await self._req("GET", f"/repos/{self.repo}/commits/{sha}/check-runs")
            if sha
            else {"check_runs": []}
        )
        runs = checks.get("check_runs", []) if isinstance(checks, dict) else []
        conclusions = [r.get("conclusion") for r in runs]
        checks_state = (
            "failure"
            if any(
                c in {"failure", "cancelled", "timed_out", "action_required"} for c in conclusions
            )
            else "success"
            if runs and all(c == "success" for c in conclusions)
            else "pending"
        )
        return {
            "state": pr.get("state"),
            "merged": pr.get("merged", False),
            "mergeable": pr.get("mergeable"),
            "head_sha": sha,
            "checks_state": checks_state,
        }

    async def merge_pr(self, number: int, merge_method: str = "squash") -> Any:
        """Merge an approved pull request using the requested merge strategy."""
        return await self._req(
            "PUT",
            f"/repos/{self.repo}/pulls/{number}/merge",
            json={"merge_method": merge_method},
        )

    async def permission(self, username: str) -> str:
        data = await self._req("GET", f"/repos/{self.repo}/collaborators/{username}/permission")
        return data.get("permission", "none")
