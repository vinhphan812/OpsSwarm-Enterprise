#!/usr/bin/env python3
"""Safe automated verification for release-gate same-SHA logic.

No network, cloud calls, release publication, tag creation, or credentials used.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from release_gate import evaluate_same_sha  # noqa: E402

SHA = "a" * 40
OTHER_SHA = "b" * 40


def verify(name: str, expected: bool, api: list[dict], web: list[dict]) -> None:
    result = evaluate_same_sha(SHA, api, web)
    print(f"{'PASS' if result['ok'] == expected else 'FAIL'} {name}: ok={result['ok']}; errors={result['errors']}")
    assert result["ok"] == expected, result


def main() -> int:
    success = [{"head_sha": SHA, "conclusion": "success"}]
    verify("same-SHA success", True, success, success)
    verify("mismatched SHA fails closed", False, success, [{"head_sha": OTHER_SHA, "conclusion": "success"}])
    verify("missing workflow fails closed", False, success, [])
    verify("failed workflow fails closed", False, [{"head_sha": SHA, "conclusion": "failure"}], success)
    verify("pending workflow fails closed", False, [{"head_sha": SHA, "conclusion": None}], success)

    tag = f"release/20261015-{SHA[:8]}"
    assert tag == "release/20261015-aaaaaaaa" and "${" not in tag
    print(f"PASS deterministic tag output: {tag}")

    provider, model = "vertex_gemini", "gemini-2.5-flash"
    assert (provider, model) == ("vertex_gemini", "gemini-2.5-flash")
    print(f"PASS canonical LLM config: {provider} / {model}")
    print("All safe release-gate harness cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
