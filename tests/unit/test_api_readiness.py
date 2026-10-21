"""Unit tests for local readiness, ingress gating, and graceful drain."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from opsswarm.runtime import ReadinessManager


@pytest.fixture(autouse=True)
def reset_readiness():
    """Keep the application singleton isolated across test modules."""
    import sys

    import opsswarm.runtime as runtime

    def _install(manager: ReadinessManager) -> None:
        runtime.readiness = manager
        # api resolves the manager through runtime.get_readiness(), so replacing
        # the module attribute is sufficient. Keep the legacy module-level
        # attribute in sync for any consumer that still reads it directly.
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

    async def set_draining() -> None:
        await runtime.readiness.initiate_drain()

    asyncio.run(set_draining())

    for path in ("/webhooks/github", "/hooks/monitoring"):
        response = client.post(path, json={})
        assert response.status_code == 503
        assert response.json()["detail"] == "Service is draining"
