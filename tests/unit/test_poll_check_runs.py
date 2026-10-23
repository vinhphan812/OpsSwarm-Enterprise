"""Failure-path tests for the required-checks bridge poller."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest


SPEC = importlib.util.spec_from_file_location(
    "poll_check_runs", Path(__file__).parents[2] / "scripts" / "poll_check_runs.py"
)
assert SPEC is not None and SPEC.loader is not None
poller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(poller)


class FakeResponse:
    def __init__(self, payload: dict, link: str = "") -> None:
        self.payload = payload
        self.headers = {"Link": link}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, *_: object) -> bytes:
        return json.dumps(self.payload).encode()


def completed(name: str, conclusion: str = "success") -> dict:
    return {"name": name, "status": "completed", "conclusion": conclusion}


def test_fetch_all_check_runs_follows_next_page() -> None:
    responses = iter(
        [
            FakeResponse(
                {"total_count": 2, "check_runs": [completed("first")]},
                '<https://example.test/page-2>; rel="next"',
            ),
            FakeResponse({"total_count": 2, "check_runs": [completed("second")]},),
        ]
    )

    runs = poller.fetch_all_check_runs(
        "owner/repo", "sha", {}, opener=lambda *_args, **_kwargs: next(responses), sleeper=lambda _: None
    )

    assert [run["name"] for run in runs] == ["first", "second"]


def test_fetch_all_check_runs_rejects_incomplete_pagination() -> None:
    response = FakeResponse({"total_count": 2, "check_runs": [completed("only")]})

    with pytest.raises(poller.CheckRunFetchError, match="Incomplete"):
        poller.fetch_all_check_runs(
            "owner/repo", "sha", {}, opener=lambda *_args, **_kwargs: response, sleeper=lambda _: None
        )


@pytest.mark.parametrize(
    ("runs", "expected", "passed", "pending"),
    [
        ([completed("gate")], ["gate"], True, False),
        ([completed("gate"), completed("gate")], ["gate"], False, False),
        ([completed("other")], ["gate"], False, True),
        ([{"name": "gate", "status": "in_progress", "conclusion": None}], ["gate", "other"], False, True),
        ([completed("gate", "failure")], ["gate"], False, False),
    ],
)
def test_evaluate_checks_fails_closed(
    runs: list[dict], expected: list[str], passed: bool, pending: bool
) -> None:
    assert poller.evaluate_checks(runs, expected) == (passed, pending)


def test_poll_checks_returns_failure_after_repeated_502() -> None:
    error = HTTPError("https://api.github.com", 502, "bad gateway", {}, None)

    assert (
        poller.poll_checks(
            "owner/repo",
            "sha",
            ["gate"],
            opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
            sleeper=lambda _: None,
        )
        == 1
    )


def test_poll_checks_succeeds_only_for_complete_success_set() -> None:
    response = FakeResponse({"total_count": 1, "check_runs": [completed("gate")]})

    assert (
        poller.poll_checks(
            "owner/repo",
            "sha",
            ["gate"],
            opener=lambda *_args, **_kwargs: response,
            sleeper=lambda _: None,
        )
        == 0
    )
