from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .errors import sanitize_for_log

import logging

logger = logging.getLogger(__name__)

# ADR-028: SSRF mitigation — only these base URLs are permitted.
# GitHub Enterprise instances must be added here explicitly; no arbitrary URLs accepted.
# http://127.0.0.1 is allowed ONLY for local test fixtures (e.g. e2e test servers).
_ALLOWED_BASE_URLS: frozenset[str] = frozenset({
    "https://api.github.com",
    "https://github.com/api/v3",
    "http://127.0.0.1",
})

# ADR-028: max_keepalive_connections=1 and max_connections=2 keep the transport
# scoped to a single logical channel, preventing connection-pooling abuse.
_TRANSPORT_LIMITS = httpx.Limits(max_keepalive_connections=1, max_connections=2)

# ADR-028: conservative timeout — bounds both overall request and TCP connect.
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# ADR-028: repo must match owner/repo (alphanumeric, hyphens, underscores).
_REPO_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9._-]+$")


class GitHubClient:
    def __init__(
        self,
        token: str,
        repo: str,
        base_url: str = "https://api.github.com",
        verify: bool | str = True,
    ):
        if base_url not in _ALLOWED_BASE_URLS:
            raise ValueError(
                f"base_url must be one of {sorted(_ALLOWED_BASE_URLS)!r}; "
                f"got {base_url!r}. "
                "See ADR-028 for GitHub Enterprise allowlist policy."
            )
        if not _REPO_PATTERN.match(repo):
            raise ValueError(
                f"repo must be in 'owner/repo' format; got {repo!r}."
            )
        self.repo = repo
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
            verify=True,  # ADR-028: hardcoded — disables CodeQL py/request-without-cert-validation
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
        checks = await self._req(
            "GET", f"/repos/{self.repo}/commits/{sha}/check-runs"
        ) if sha else {"check_runs": []}
        runs = checks.get("check_runs", []) if isinstance(checks, dict) else []
        conclusions = [r.get("conclusion") for r in runs]
        checks_state = (
            "failure" if any(c in {"failure", "cancelled", "timed_out", "action_required"} for c in conclusions)
            else "success" if runs and all(c == "success" for c in conclusions)
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
