from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: str, repo: str, base_url: str = "https://api.github.com"):
        self.repo = repo
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
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
                path,
                e.response.text[:500],
            )
            raise PermissionError(
                f"GitHub API returned {e.response.status_code} for {method} {path}"
            ) from None
        except PermissionError:
            raise  # already sanitized
        except Exception as e:
            logger.exception("GitHub API unexpected error: method=%s path=%s", method, path)
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
