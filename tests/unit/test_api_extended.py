"""Extended tests for opsswarm.api module - covers uncovered endpoints.

Auth setup: opsswarm.auth.verify_scoped_bearer is patched to return "opsswarm:admin"
for all requests so tests focus on endpoint logic rather than auth mechanics.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _setup_env():
    """Ensure OPSWARM_RUNTIME_SECRET is present and auth module is loaded."""
    import opsswarm.auth as auth_module

    os.environ.setdefault("OPSWARM_RUNTIME_SECRET", "test-secret")
    auth_module.reload_auth_config()
    auth_module._monitoring_limiter._hits.clear()
    yield
    auth_module.reload_auth_config()
    auth_module._monitoring_limiter._hits.clear()


class TestRunEndpointWithData:
    def test_run_found(self):
        """GET /runs/{issue_number} returns the correct run record."""
        import opsswarm.api as api_module
        import opsswarm.auth as auth_module

        orig_verify = auth_module.verify_scoped_bearer
        try:

            async def mock_verify(request, authorization=None):
                return "opsswarm:admin"

            auth_module.verify_scoped_bearer = mock_verify

            from opsswarm.models import RunRecord, RunState

            orig_engine = api_module.engine
            mock_run = RunRecord(run_id="r1", issue_number=42, state=RunState.INVESTIGATING)
            mock_engine = MagicMock()
            mock_engine.runs = {42: mock_run}
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            try:
                client = TestClient(api_module.app)
                response = client.get("/runs/42")
                assert response.status_code == 200
                assert response.json()["run_id"] == "r1"
            finally:
                api_module.engine = orig_engine
        finally:
            auth_module.verify_scoped_bearer = orig_verify


class TestEvidenceEndpointWithData:
    def test_evidence_returns_list(self):
        """GET /runs/{issue_number}/evidence returns the evidence list."""
        import opsswarm.api as api_module
        import opsswarm.auth as auth_module

        orig_verify = auth_module.verify_scoped_bearer
        try:

            async def mock_verify(request, authorization=None):
                return "opsswarm:admin"

            auth_module.verify_scoped_bearer = mock_verify

            from opsswarm.models import RunRecord, RunState
            from opsswarm.evidence import EvidenceStore

            orig_engine = api_module.engine
            mock_run = RunRecord(run_id="r2", issue_number=10, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.list.return_value = [{"id": "EV-1", "kind": "finding"}]
            mock_engine = MagicMock()
            mock_engine.runs = {10: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            try:
                client = TestClient(api_module.app)
                response = client.get("/runs/10/evidence")
                assert response.status_code == 200
                assert len(response.json()) == 1
            finally:
                api_module.engine = orig_engine
        finally:
            auth_module.verify_scoped_bearer = orig_verify


class TestCheckpointEndpointWithData:
    def test_checkpoint_none(self):
        """GET /runs/{issue_number}/checkpoint returns has_checkpoint=False when no checkpoint."""
        import opsswarm.api as api_module
        import opsswarm.auth as auth_module

        orig_verify = auth_module.verify_scoped_bearer
        try:

            async def mock_verify(request, authorization=None):
                return "opsswarm:admin"

            auth_module.verify_scoped_bearer = mock_verify

            from opsswarm.models import RunRecord, RunState
            from opsswarm.evidence import EvidenceStore

            orig_engine = api_module.engine
            mock_run = RunRecord(run_id="r3", issue_number=5, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.get_last_checkpoint.return_value = None
            mock_engine = MagicMock()
            mock_engine.runs = {5: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            try:
                client = TestClient(api_module.app)
                response = client.get("/runs/5/checkpoint")
                assert response.status_code == 200
                data = response.json()
                assert data["has_checkpoint"] is False
            finally:
                api_module.engine = orig_engine
        finally:
            auth_module.verify_scoped_bearer = orig_verify

    def test_checkpoint_found(self):
        """GET /runs/{issue_number}/checkpoint returns checkpoint data when present."""
        import opsswarm.api as api_module
        import opsswarm.auth as auth_module

        orig_verify = auth_module.verify_scoped_bearer
        try:

            async def mock_verify(request, authorization=None):
                return "opsswarm:admin"

            auth_module.verify_scoped_bearer = mock_verify

            from opsswarm.models import RunRecord, RunState
            from opsswarm.evidence import EvidenceStore

            orig_engine = api_module.engine
            mock_run = RunRecord(run_id="r4", issue_number=6, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.get_last_checkpoint.return_value = {
                "id": "EV-checkpoint",
                "kind": "checkpoint",
                "payload": {"checkpoint_type": "STATE_TRANSITION"},
            }
            mock_engine = MagicMock()
            mock_engine.runs = {6: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            try:
                client = TestClient(api_module.app)
                response = client.get("/runs/6/checkpoint")
                assert response.status_code == 200
                assert response.json()["has_checkpoint"] is True
            finally:
                api_module.engine = orig_engine
        finally:
            auth_module.verify_scoped_bearer = orig_verify


class TestResumeEndpointWithData:
    def test_resume_no_checkpoint(self):
        """POST /runs/{issue_number}/resume -> 400 when no checkpoint available."""
        import opsswarm.api as api_module
        import opsswarm.auth as auth_module

        orig_verify = auth_module.verify_scoped_bearer
        try:

            async def mock_verify(request, authorization=None):
                return "opsswarm:admin"

            auth_module.verify_scoped_bearer = mock_verify

            from opsswarm.models import RunRecord, RunState
            from opsswarm.evidence import EvidenceStore

            orig_engine = api_module.engine
            mock_run = RunRecord(run_id="r5", issue_number=7, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.get_last_checkpoint.return_value = None
            mock_engine = MagicMock()
            mock_engine.runs = {7: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            try:
                client = TestClient(api_module.app)
                response = client.post("/runs/7/resume")
                assert response.status_code == 400
            finally:
                api_module.engine = orig_engine
        finally:
            auth_module.verify_scoped_bearer = orig_verify

    def test_resume_with_checkpoint(self):
        """POST /runs/{issue_number}/resume -> 200 with checkpoint data."""
        import opsswarm.api as api_module
        import opsswarm.auth as auth_module

        orig_verify = auth_module.verify_scoped_bearer
        try:

            async def mock_verify(request, authorization=None):
                return "opsswarm:admin"

            auth_module.verify_scoped_bearer = mock_verify

            from opsswarm.models import RunRecord, RunState
            from opsswarm.evidence import EvidenceStore

            orig_engine = api_module.engine
            mock_run = RunRecord(run_id="r6", issue_number=8, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.get_last_checkpoint.return_value = {
                "payload": {"checkpoint_type": "HUMAN_GATE", "state": "WAITING_APPROVAL"}
            }
            mock_engine = MagicMock()
            mock_engine.runs = {8: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            try:
                client = TestClient(api_module.app)
                response = client.post("/runs/8/resume")
                assert response.status_code == 200
                data = response.json()
                assert data["resumed"] is True
                assert data["checkpoint_type"] == "HUMAN_GATE"
            finally:
                api_module.engine = orig_engine
        finally:
            auth_module.verify_scoped_bearer = orig_verify


class TestMonitoringEndpoint:
    def test_monitoring_accepted(self):
        """POST /hooks/monitoring creates a GitHub issue and returns issue number."""
        import opsswarm.api as api_module
        import opsswarm.auth as auth_module
        import opsswarm.webhook as webhook_module

        orig_engine = api_module.engine
        orig_gh = api_module.gh
        orig_api_verify = api_module.verify_signature
        orig_webhook_verify = webhook_module.verify_signature
        orig_auth_verify = auth_module.verify_scoped_bearer
        try:

            async def mock_verify(request, authorization=None):
                return "opsswarm:admin"

            auth_module.verify_scoped_bearer = mock_verify
            # Bypass HMAC signature check (GITHUB_WEBHOOK_SECRET may not be set)
            api_module.verify_signature = lambda *a, **k: True
            webhook_module.verify_signature = lambda *a, **k: True

            mock_ev = MagicMock()
            mock_gh = MagicMock()
            mock_gh.create_issue = AsyncMock(return_value={"number": 99})

            mock_engine = MagicMock()
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)

            api_module.engine = mock_engine
            api_module.gh = mock_gh
            try:
                client = TestClient(api_module.app)
                response = client.post(
                    "/hooks/monitoring",
                    json={
                        "title": "DB down",
                        "service": "postgres-primary",
                        "symptom": "High latency",
                        "customer_impact": "All users",
                        "environment": "production",
                        "observed_since": "2026-09-23T10:00:00Z",
                    },
                )
                assert response.status_code == 200
                assert response.json()["accepted"] is True
                assert response.json()["issue_number"] == 99
            finally:
                api_module.engine = orig_engine
                api_module.gh = orig_gh
        finally:
            auth_module.verify_scoped_bearer = orig_auth_verify
            api_module.verify_signature = orig_api_verify
            webhook_module.verify_signature = orig_webhook_verify
