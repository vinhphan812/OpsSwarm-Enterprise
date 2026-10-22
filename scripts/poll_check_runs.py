#!/usr/bin/env python3
import os
import sys
import time
import json
import urllib.request
import urllib.error

def poll_checks(repo, head_sha, expected_checks, max_attempts=60, sleep_seconds=10):
    url = f"https://api.github.com/repos/{repo}/commits/{head_sha}/check-runs?per_page=100"
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(1, max_attempts + 1):
        json_data = None
        # Retry inner loop for transient errors (5xx, 429, network exceptions)
        for inner in range(5):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    json_data = json.load(resp)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                status_code = getattr(e, 'code', None)
                if status_code and status_code < 500 and status_code != 429:
                    print(f"Non-transient HTTP error {status_code}: {e}", file=sys.stderr)
                    raise
                backoff = 2 ** inner
                print(f"Transient fetch error on attempt {attempt} (inner {inner}): {e}. Retrying in {backoff}s...", file=sys.stderr)
                time.sleep(backoff)
            except Exception as e:
                print(f"Unexpected fetch error on attempt {attempt} (inner {inner}): {e}. Retrying...", file=sys.stderr)
                time.sleep(2 ** inner)

        if json_data is None:
            print(f"Attempt {attempt}: failed to fetch check-runs after retries. Treating as pending.", file=sys.stderr)
            pending = 1
            failed = 0
        else:
            check_runs = json_data.get("check_runs", [])
            pending = 0
            failed = 0

            for check in expected_checks:
                # Find matching runs sorted by started_at // created_at last (deterministic)
                matching = [r for r in check_runs if r.get("name") == check]
                if not matching:
                    state = "missing"
                else:
                    matching.sort(key=lambda x: x.get("started_at") or x.get("created_at") or "")
                    last_run = matching[-1]
                    conclusion = last_run.get("conclusion")
                    status = last_run.get("status")
                    if not conclusion:
                        state = status or "pending"
                    else:
                        state = conclusion

                print(f"{check}: {state}")

                if state in {"success", "neutral", "skipped"}:
                    pass
                elif state in {"missing", "queued", "in_progress", "requested", "waiting", "pending", "null"}:
                    pending = 1
                else:
                    failed = 1

        if failed == 1:
            print("One or more canonical CI checks failed.", file=sys.stderr)
            sys.exit(1)

        if pending == 0:
            print("All canonical CI checks passed.")
            sys.exit(0)

        if attempt < max_attempts:
            time.sleep(sleep_seconds)

    print("Timed out waiting for canonical CI checks.", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Poll GitHub check-runs with resilience")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--checks", nargs="+", required=True)
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--sleep", type=int, default=10)
    args = parser.parse_args()

    poll_checks(args.repo, args.head_sha, args.checks, args.max_attempts, args.sleep)
