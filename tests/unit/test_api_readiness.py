"""Unit tests for local readiness, ingress gating, and graceful drain."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from opsswarm.evidence import EvidenceStore
from opsswarm.models import RunState
from opsswarm.runtime import ReadinessManager
from opsswarm.store import RunStore


@pytest.fixture(autouse=True)
def reset_readiness():
    """Keep the application singleton isolated across test modules."""
    import sys

    import opsswarm.runtime as runtime

    def _install(manager: ReadinessManager) -> None:
        runtime.readiness = manager
        api_module = sys.modules.get("opsswarm.api")
        if api_module is not None and hasattr(api_module, "readiness"):
            api_module.readiness = manager

    _install(ReadinessManager())
    yield
    _install(ReadinessManager())


@pytest.fixture
def client():
    """Provide a request client with external API collaborators stubbed."""
    import opsswarm.api as api_module

    original_engine = api_module.engine
    original_gh = api_module.gh
    original_oc = api_module.oc
    engine = MagicMock()
    engine.runs = {}
    engine.start_issue = AsyncMock()
    engine.handle_comment = AsyncMock()
    api_module.engine = engine
    api_module.gh = MagicMock()
    api_module.oc = MagicMock()
    try:
        yield TestClient(api_module.app, raise_server_exceptions=False)
    finally:
        api_module.engine = original_engine
        api_module.gh = original_gh
        api_module.oc = original_oc


async def test_ready_only_after_startup_preflight(client):
    assert client.get("/ready").status_code == 503

    import opsswarm.api as api_module

    await api_module._startup_auth_check()
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_shutdown_drain_waits_for_accepted_dispatch_and_rejects_new_work():
    readiness = ReadinessManager()
    await readiness.startup_complete()
    await readiness.begin_dispatch()

    drain_task = asyncio.create_task(readiness.initiate_drain())
    await asyncio.sleep(0)

    assert readiness.draining is True
    assert readiness.ready is False
    assert drain_task.done() is False

    with pytest.raises(Exception) as blocked:
        await readiness.begin_dispatch()
    assert getattr(blocked.value, "status_code", None) == 503

    await readiness.end_dispatch()
    await drain_task
    assert drain_task.done() is True


async def test_background_dispatch_remains_inflight_until_work_finishes():
    readiness = ReadinessManager()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def background_work() -> None:
        entered.set()
        await release.wait()

    await readiness.start_background_dispatch(background_work())
    await entered.wait()
    drain_task = asyncio.create_task(readiness.initiate_drain())
    await asyncio.sleep(0)
    assert drain_task.done() is False

    release.set()
    await drain_task
    assert drain_task.done() is True
    assert readiness._background_tasks == set()


async def test_github_opened_dispatch_remains_tracked_after_handler_returns(monkeypatch):
    import opsswarm.api as api_module
    import opsswarm.runtime as runtime

    readiness = ReadinessManager()
    await readiness.startup_complete()
    runtime.readiness = readiness
    entered = asyncio.Event()
    release = asyncio.Event()

    async def background_work(*args) -> None:
        entered.set()
        await release.wait()

    monkeypatch.setattr(api_module.engine, "start_issue", background_work)
    monkeypatch.setattr(api_module, "verify_signature", lambda *args: True)

    class Request:
        async def body(self):
            return b"{}"

        async def json(self):
            return {"action": "opened", "issue": {"number": 42}}

    response = await api_module.github_webhook(
        Request(), x_github_event="issues", x_hub_signature_256="ok", x_github_delivery="delivery-1"
    )
    assert response == {"accepted": True, "issue": 42}
    await entered.wait()

    drain_task = asyncio.create_task(readiness.initiate_drain())
    await asyncio.sleep(0)
    try:
        assert drain_task.done() is False
    finally:
        release.set()
    await asyncio.wait_for(drain_task, timeout=1)


async def test_monitoring_dispatch_remains_tracked_after_handler_returns(monkeypatch):
    import opsswarm.api as api_module
    import opsswarm.auth as auth_module
    import opsswarm.runtime as runtime

    readiness = ReadinessManager()
    await readiness.startup_complete()
    runtime.readiness = readiness
    entered = asyncio.Event()
    release = asyncio.Event()

    async def background_work(*args) -> None:
        entered.set()
        await release.wait()

    monkeypatch.setattr(api_module.engine, "start_issue", background_work)
    monkeypatch.setattr(api_module, "check_monitoring_body_size", lambda *args: None)
    monkeypatch.setattr(api_module, "check_monitoring_rate_limit", lambda *args: (True, 0))
    monkeypatch.setattr(api_module, "_get_real_client_ip", lambda *args: "127.0.0.1")
    monkeypatch.setattr(api_module, "_probe_scope_from_bearer", AsyncMock(return_value=auth_module.SCOPE_MONITOR))
    monkeypatch.setattr(api_module, "verify_scoped_bearer", AsyncMock(return_value=auth_module.SCOPE_MONITOR))
    monkeypatch.setattr(api_module, "verify_signature", lambda *args: False)
    monkeypatch.setattr(api_module, "gh", MagicMock())
    monkeypatch.setattr(api_module.gh, "create_issue", AsyncMock(return_value={"number": 43}))

    class Request:
        headers = {"content-length": "2", "Authorization": "Bearer test"}

        async def body(self):
            return b"{}"

        async def json(self):
            return {"title": "Alert", "service": "api"}

    response = await api_module.monitoring_event(Request())
    assert response == {"accepted": True, "issue_number": 43}
    await entered.wait()

    drain_task = asyncio.create_task(readiness.initiate_drain())
    await asyncio.sleep(0)
    try:
        assert drain_task.done() is False
    finally:
        release.set()
    await asyncio.wait_for(drain_task, timeout=1)


async def test_background_dispatch_cancellation_releases_tracking():
    readiness = ReadinessManager()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def background_work() -> None:
        entered.set()
        await release.wait()

    await readiness.start_background_dispatch(background_work())
    await entered.wait()
    task = next(iter(readiness._background_tasks))
    drain_task = asyncio.create_task(readiness.initiate_drain())
    await asyncio.sleep(0)
    assert drain_task.done() is False

    task.cancel()
    await asyncio.wait_for(drain_task, timeout=1)
    assert readiness._drained.is_set()


async def test_cancelled_started_dispatch_is_recorded_for_reconciliation(tmp_path: Path):
    """A started dispatch writes durable UNKNOWN state and evidence before release."""
    store = RunStore(str(tmp_path))
    evidence = EvidenceStore(str(tmp_path))
    readiness = ReadinessManager(store=store, evidence=evidence)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def background_work() -> None:
        entered.set()
        await release.wait()

    await readiness.start_background_dispatch(
        background_work(), label="issue:42:opened", issue_number=42, persist_accepted=True
    )
    await entered.wait()
    task = next(iter(readiness._background_tasks))

    task.cancel()
    await asyncio.wait_for(readiness._drained.wait(), timeout=1)
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    assert readiness.abandoned_dispatches == ["issue:42:opened"]
    marker = next(run for run in store.load_all() if run.issue_number == 42)
    assert marker.state == RunState.INVESTIGATING
    assert marker.command_outcomes["issue:42:opened"] == "unknown"
    checkpoint = store.load_checkpoint(marker.run_id)
    assert checkpoint is not None and checkpoint.checkpoint_state == "shutdown_drain_timeout"
    evidence_path = tmp_path / "evidence" / f"{marker.run_id}.jsonl"
    events = [
        json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["kind"] == "S5.dispatch.abandoned"


async def test_cancelled_dispatch_that_never_started_is_not_abandoned():
    """Cancelling work before its first step abandons nothing: it never ran."""
    readiness = ReadinessManager()
    release = asyncio.Event()

    async def background_work() -> None:
        await release.wait()

    await readiness.start_background_dispatch(background_work(), label="issue:43:opened")
    task = next(iter(readiness._background_tasks))
    task.cancel()
    await asyncio.wait_for(readiness._drained.wait(), timeout=1)
    await asyncio.sleep(0)

    assert readiness.abandoned_dispatches == []


async def test_drain_reports_success_when_accepted_work_finishes():
    readiness = ReadinessManager()
    await readiness.startup_complete()
    await readiness.begin_dispatch()

    async def finish() -> None:
        await asyncio.sleep(0)
        await readiness.end_dispatch()

    finishing = asyncio.create_task(finish())
    assert await readiness.initiate_drain(timeout=5) is True
    await finishing
    assert readiness.abandoned_dispatches == []


async def test_drain_timeout_configuration_rejects_invalid_values(monkeypatch, caplog):
    from opsswarm.runtime import (
        DEFAULT_DRAIN_TIMEOUT_SECONDS,
        DRAIN_TIMEOUT_ENV,
        _configured_drain_timeout,
    )

    for value in ("bad", "nan", "inf", "-1"):
        monkeypatch.setenv(DRAIN_TIMEOUT_ENV, value)
        with caplog.at_level("WARNING"):
            assert _configured_drain_timeout() == DEFAULT_DRAIN_TIMEOUT_SECONDS

    monkeypatch.setenv(DRAIN_TIMEOUT_ENV, "0.25")
    assert _configured_drain_timeout() == 0.25


async def test_drain_deadline_records_every_inflight_dispatch_as_abandoned(tmp_path: Path):
    """A hung dispatch writes durable markers for every accepted operation."""
    store = RunStore(str(tmp_path))
    evidence = EvidenceStore(str(tmp_path))
    readiness = ReadinessManager(store=store, evidence=evidence)
    await readiness.startup_complete()

    hang = asyncio.Event()

    async def hung_work() -> None:
        await hang.wait()

    await readiness.start_background_dispatch(
        hung_work(), label="issue:44:opened", issue_number=44, persist_accepted=True
    )
    pending = list(readiness._background_tasks)
    await readiness.begin_dispatch()

    assert await readiness.initiate_drain(timeout=0.05) is False
    assert readiness.abandoned_dispatches == ["issue:44:opened", "unlabelled"]
    assert readiness.inflight == 2

    markers = [
        run for run in store.load_all() if run.error and "interrupted during shutdown" in run.error
    ]
    assert len(markers) == 2
    assert all(run.command_outcomes for run in markers)
    for run in markers:
        checkpoint = store.load_checkpoint(run.run_id)
        assert checkpoint is not None
        assert checkpoint.checkpoint_state == "shutdown_drain_timeout"
        evidence_path = tmp_path / "evidence" / f"{run.run_id}.jsonl"
        assert evidence_path.exists()

    hang.set()
    await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0)
    await readiness.end_dispatch()
    await asyncio.sleep(0)


async def test_shutdown_handler_logs_the_dispatch_it_abandoned(monkeypatch, caplog):
    """The application shutdown hook reports abandoned work, not just count."""
    import opsswarm.api as api_module
    import opsswarm.runtime as runtime

    readiness = ReadinessManager()
    await readiness.startup_complete()
    runtime.readiness = readiness

    hang = asyncio.Event()

    async def hung_work() -> None:
        await hang.wait()

    await readiness.start_background_dispatch(hung_work(), label="issue:45:opened")
    monkeypatch.setenv(runtime.DRAIN_TIMEOUT_ENV, "0.05")

    with caplog.at_level("ERROR"):
        await api_module._shutdown_drain()

    assert "issue:45:opened" in caplog.text
    hang.set()
    await asyncio.sleep(0)


async def test_background_dispatch_cancelled_before_start_releases_tracking():
    readiness = ReadinessManager()

    async def background_work() -> None:
        return None

    await readiness.start_background_dispatch(background_work())
    task = next(iter(readiness._background_tasks))
    task.cancel()
    await asyncio.wait_for(readiness._drained.wait(), timeout=1)
    await asyncio.sleep(0)
    assert readiness._inflight == 0


async def test_background_dispatch_creation_failure_rolls_back_tracking(monkeypatch):
    readiness = ReadinessManager()
    await readiness.startup_complete()

    async def background_work() -> None:
        return None

    work = background_work()

    def fail_create_task(coroutine):
        raise RuntimeError("task creation failed")

    monkeypatch.setattr(asyncio, "create_task", fail_create_task)
    with pytest.raises(RuntimeError, match="task creation failed"):
        await readiness.start_background_dispatch(work)

    assert readiness._drained.is_set()
    assert readiness._inflight == 0
    assert readiness._background_tasks == set()


async def test_background_dispatch_tracking_failure_leaves_no_reservation(monkeypatch):
    """A failure while reserving the slot must not strand readiness state."""
    readiness = ReadinessManager()
    await readiness.startup_complete()

    closed = False

    class Work:
        """Awaitable that records whether it was closed without being started."""

        def __await__(self):
            async def _run():
                return None

            return _run().__await__()

        def close(self) -> None:
            nonlocal closed
            closed = True

    work = Work()

    async def fail_track() -> None:
        raise RuntimeError("tracking failed")

    monkeypatch.setattr(readiness, "_track_dispatch", fail_track)

    try:
        await readiness.start_background_dispatch(work)
    except RuntimeError as exc:
        assert str(exc) == "tracking failed"
    else:
        pytest.fail("tracking failure was not raised")

    assert closed is True
    assert readiness._inflight == 0
    assert readiness._drained.is_set()


async def test_decorator_tracks_inflight_request_until_handler_finishes():
    import opsswarm.runtime as runtime

    entered = asyncio.Event()
    release = asyncio.Event()

    @runtime.check_draining
    async def handler() -> str:
        entered.set()
        await release.wait()
        return "completed"

    task = asyncio.create_task(handler())
    await entered.wait()
    drain_task = asyncio.create_task(runtime.readiness.initiate_drain())
    await asyncio.sleep(0)

    assert runtime.readiness.draining is True
    assert drain_task.done() is False

    release.set()
    assert await task == "completed"
    await drain_task


def test_draining_blocks_all_mutating_endpoints(client):
    import opsswarm.runtime as runtime

    original_readiness = runtime.readiness
    readiness = ReadinessManager()
    runtime.readiness = readiness

    async def set_draining() -> None:
        await readiness.startup_complete()
        await readiness.initiate_drain()

    asyncio.run(set_draining())
    try:
        for path in ("/webhooks/github", "/hooks/monitoring"):
            response = client.post(path, json={})
            assert response.status_code == 503
            assert response.json()["detail"] == "Service is draining"
    finally:
        runtime.readiness = original_readiness
