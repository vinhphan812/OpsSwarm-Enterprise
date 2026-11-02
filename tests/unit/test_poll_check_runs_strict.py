"""Unit tests for the required-check bridge's strict check semantics."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "poll_check_runs_strict", Path(__file__).parents[2] / "scripts" / "poll_check_runs.py"
)
assert SPEC is not None and SPEC.loader is not None
poller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(poller)


def run(conclusion: str) -> dict:
    return {"name": "HA PostgreSQL schema and concurrency", "status": "completed", "conclusion": conclusion}


@pytest.mark.parametrize("conclusion", ["skipped", "neutral", "cancelled", "failure", "timed_out"])
def test_strict_check_rejects_every_conclusion_other_than_success(conclusion: str) -> None:
    passed, pending = poller.evaluate_checks(
        [run(conclusion)], ["HA PostgreSQL schema and concurrency"], ["HA PostgreSQL schema and concurrency"]
    )
    assert not passed
    assert not pending


def test_strict_check_accepts_success() -> None:
    passed, pending = poller.evaluate_checks(
        [run("success")], ["HA PostgreSQL schema and concurrency"], ["HA PostgreSQL schema and concurrency"]
    )
    assert passed
    assert not pending


def test_non_strict_checks_keep_existing_skipped_semantics() -> None:
    passed, pending = poller.evaluate_checks(
        [run("skipped")], ["HA PostgreSQL schema and concurrency"]
    )
    assert passed
    assert not pending
