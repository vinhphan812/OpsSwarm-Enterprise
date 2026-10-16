#!/usr/bin/env python3
"""Fail-closed evaluator for the release gate's required same-SHA workflows."""
from __future__ import annotations

import argparse
import json
from typing import Any


def _errors_for(label: str, sha: str, runs: list[dict[str, Any]]) -> list[str]:
    """A release is clear only if this workflow has a successful exact-SHA run."""
    exact = [run for run in runs if run.get("head_sha") == sha]
    if not exact:
        observed = sorted({str(run.get("head_sha") or "<empty>") for run in runs})
        if not observed:
            return [f"{label}: required workflow is absent for SHA {sha}"]
        return [f"{label}: SHA mismatch; expected {sha}, observed {', '.join(observed)}"]
    conclusions = {str(run.get("conclusion") or "pending") for run in exact}
    if "success" not in conclusions:
        return [f"{label}: required workflow did not succeed for SHA {sha} (conclusion={', '.join(sorted(conclusions))})"]
    return []


def evaluate_same_sha(sha: str, api_runs: list[dict[str, Any]], web_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a deterministic decision. Missing, mismatch, pending, or failure fails."""
    errors = ["gate SHA is empty"] if not sha else []
    if sha:
        errors += _errors_for("API CI", sha, api_runs)
        errors += _errors_for("Web CI / CD", sha, web_runs)
    return {"ok": not errors, "sha": sha, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--api-runs", required=True)
    parser.add_argument("--web-runs", required=True)
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    try:
        decision = evaluate_same_sha(args.sha, json.loads(args.api_runs), json.loads(args.web_runs))
    except json.JSONDecodeError as exc:
        decision = {"ok": False, "sha": args.sha, "errors": [f"invalid Actions API JSON: {exc}"]}
    if args.github_output:
        print(f"both_passed={'true' if decision['ok'] else 'false'}")
        print(f"gate_sha={decision['sha']}")
        print(f"error={' ; '.join(decision['errors'])}")
    else:
        print(json.dumps(decision, sort_keys=True))
    return 0 if decision["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
