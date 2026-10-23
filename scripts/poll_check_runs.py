#!/usr/bin/env python3
"""Fail-closed polling for the exact GitHub check runs required by the bridge."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from typing import Any

SUCCESSFUL_CONCLUSIONS = {"success", "neutral", "skipped"}
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


class CheckRunFetchError(RuntimeError):
    """The complete set of check runs could not be read reliably."""


def _next_page(response: Any) -> str | None:
    for item in response.headers.get("Link", "").split(","):
        parts = [part.strip() for part in item.split(";")]
        if len(parts) >= 2 and 'rel="next"' in parts[1]:
            return parts[0].removeprefix("<").removesuffix(">")
    return None


def _request_json(url: str, headers: dict[str, str], opener: Callable[..., Any], sleeper: Callable[[float], None]) -> tuple[dict[str, Any], str | None]:
    error = "unknown error"
    for retry in range(5):
        try:
            request = urllib.request.Request(url, headers=headers)
            with opener(request, timeout=30) as response:  # nosec B310: fixed GitHub API origin
                return json.load(response), _next_page(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in TRANSIENT_HTTP_STATUSES:
                raise CheckRunFetchError(f"GitHub API returned HTTP {exc.code}") from exc
            error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            error = str(exc)
        if retry < 4:
            delay = 2**retry
            print(f"Transient GitHub API error ({error}); retrying in {delay}s.", file=sys.stderr)
            sleeper(delay)
    raise CheckRunFetchError(f"Unable to fetch check runs after retries: {error}")


def fetch_all_check_runs(repo: str, head_sha: str, headers: dict[str, str], opener: Callable[..., Any] = urllib.request.urlopen, sleeper: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """Fetch all ``filter=all`` pages and reject incomplete/changing results."""
    url = f"https://api.github.com/repos/{repo}/commits/{head_sha}/check-runs?per_page=100&filter=all"
    runs: list[dict[str, Any]] = []
    total: int | None = None
    visited: set[str] = set()
    while url:
        if url in visited:
            raise CheckRunFetchError("GitHub pagination loop detected")
        visited.add(url)
        payload, url = _request_json(url, headers, opener, sleeper)
        page_runs, page_total = payload.get("check_runs"), payload.get("total_count")
        if not isinstance(page_runs, list) or not isinstance(page_total, int) or any(not isinstance(run, dict) for run in page_runs):
            raise CheckRunFetchError("GitHub response omitted valid check-run pagination data")
        if total is None:
            total = page_total
        elif total != page_total:
            raise CheckRunFetchError("GitHub check-run total changed during pagination")
        runs.extend(page_runs)
    if total is None or len(runs) != total:
        raise CheckRunFetchError(f"Incomplete check-run pagination: received {len(runs)}, expected {total}")
    return runs


def evaluate_checks(check_runs: Iterable[dict[str, Any]], expected_checks: Iterable[str]) -> tuple[bool, bool]:
    """Return (passed, pending); missing, duplicates, and failures cannot pass."""
    by_name: dict[str, list[dict[str, Any]]] = {}
    for run in check_runs:
        if isinstance(run.get("name"), str):
            by_name.setdefault(run["name"], []).append(run)

    pending = failed = False
    missing: list[str] = []
    observed_expected = False
    observed_terminal = True
    for name in expected_checks:
        matches = by_name.get(name, [])
        if len(matches) != 1:
            if not matches:
                missing.append(name)
                print(f"{name}: missing")
            else:
                failed = True
                print(f"{name}: ambiguous ({len(matches)} matching check runs)")
            continue
        observed_expected = True
        status, conclusion = matches[0].get("status"), matches[0].get("conclusion")
        state = conclusion if isinstance(conclusion, str) else status or "pending"
        print(f"{name}: {state}")
        if status != "completed" or not isinstance(conclusion, str):
            pending, observed_terminal = True, False
        elif conclusion not in SUCCESSFUL_CONCLUSIONS:
            failed = True

    if missing:
        if observed_expected and observed_terminal and not pending:
            failed = True
        else:
            pending = True
    return not failed and not pending, pending and not failed


def poll_checks(repo: str, head_sha: str, expected_checks: list[str], max_attempts: int = 60, sleep_seconds: int = 10, opener: Callable[..., Any] = urllib.request.urlopen, sleeper: Callable[[float], None] = time.sleep) -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(1, max_attempts + 1):
        try:
            check_runs = fetch_all_check_runs(repo, head_sha, headers, opener, sleeper)
        except CheckRunFetchError as exc:
            print(f"Unable to verify canonical check runs: {exc}", file=sys.stderr)
            return 1
        passed, pending = evaluate_checks(check_runs, expected_checks)
        if passed:
            print("All canonical checks passed.")
            return 0
        if not pending:
            print("One or more canonical checks failed or were ambiguous.", file=sys.stderr)
            return 1
        if attempt < max_attempts:
            sleeper(sleep_seconds)
    print("Timed out waiting for canonical checks.", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed GitHub check-run bridge")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--checks", nargs="+", required=True)
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--sleep", type=int, default=10)
    args = parser.parse_args()
    return poll_checks(args.repo, args.head_sha, args.checks, args.max_attempts, args.sleep)


if __name__ == "__main__":
    raise SystemExit(main())
