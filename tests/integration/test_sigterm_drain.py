"""Integration test for real uvicorn SIGTERM shutdown and readiness drain."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
import httpx
import pytest


@pytest.mark.asyncio
async def test_uvicorn_sigterm_drain():
    # Start a uvicorn server subprocess running opsswarm.api:app
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["OPSWARM_RUNTIME_SECRET"] = "test-secret"
    env["GITHUB_TOKEN"] = "test-token"
    env["GITHUB_REPO"] = "test/test-repo"

    port = 8765
    server_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "opsswarm.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient() as client:
        # Wait for server startup
        started = False
        for _ in range(30):
            try:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    started = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        assert started, "Server failed to start"

        # Startup preflight is required for /ready
        import opsswarm.api as api_module
        await api_module._startup_auth_check()

        resp = await client.get(f"{url}/ready")
        assert resp.status_code == 200

        # Send SIGTERM to server
        server_proc.send_signal(signal.SIGTERM)

        # Poll /ready to verify it immediately returns 503 during drain or server closes connection
        draining_detected = False
        for _ in range(50):
            try:
                resp = await client.get(f"{url}/ready")
                if resp.status_code == 503:
                    draining_detected = True
                    break
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectTimeout):
                draining_detected = True
                break
            except Exception:
                pass
            await asyncio.sleep(0.2)

        # Allow graceful shutdown to complete
        try:
            server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.wait()

    assert draining_detected, "Server did not reject readiness with 503 after SIGTERM"
