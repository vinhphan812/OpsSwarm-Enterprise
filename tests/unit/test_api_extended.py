"""Extended tests for opsswarm.api module - covers uncovered endpoints."""
import asyncio
import os
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


class TestRunEndpointWithData:
    def test_run_found(self):
        import opsswarm.api as api_module
        from opsswarm.models import RunRecord, RunState
        orig = api_module.engine
        try:
            mock_run = RunRecord(run_id="r1", issue_number=42, state=RunState.INVESTIGATING)
            mock_engine = MagicMock()
            mock_engine.runs = {42: mock_run}
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            api_module.app.dependency_overrides[api_module.verify_api_key] = lambda: "mock-key"
            client = TestClient(api_module.app)
            response = client.get("/runs/42", headers={"X-OpsSwarm-API-Key": "mock-key"})
            assert response.status_code == 200
            assert response.json()["run_id"] == "r1"
        finally:
            api_module.engine = orig
            api_module.app.dependency_overrides = {}


class TestEvidenceEndpointWithData:
    def test_evidence_returns_list(self):
        import opsswarm.api as api_module
        from opsswarm.models import RunRecord, RunState
        from opsswarm.evidence import EvidenceStore
        orig = api_module.engine
        try:
            mock_run = RunRecord(run_id="r2", issue_number=10, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.list.return_value = [{"id": "EV-1", "kind": "finding"}]
            mock_engine = MagicMock()
            mock_engine.runs = {10: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            api_module.app.dependency_overrides[api_module.verify_api_key] = lambda: "mock-key"
            client = TestClient(api_module.app)
            response = client.get("/runs/10/evidence", headers={"X-OpsSwarm-API-Key": "mock-key"})
            assert response.status_code == 200
            assert len(response.json()) == 1
        finally:
            api_module.engine = orig
            api_module.app.dependency_overrides = {}


class TestCheckpointEndpointWithData:
    def test_checkpoint_none(self):
        import opsswarm.api as api_module
        from opsswarm.models import RunRecord, RunState
        from opsswarm.evidence import EvidenceStore
        orig = api_module.engine
        try:
            mock_run = RunRecord(run_id="r3", issue_number=5, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.get_last_checkpoint.return_value = None
            mock_engine = MagicMock()
            mock_engine.runs = {5: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            api_module.app.dependency_overrides[api_module.verify_api_key] = lambda: "mock-key"
            client = TestClient(api_module.app)
            response = client.get("/runs/5/checkpoint", headers={"X-OpsSwarm-API-Key": "mock-key"})
            assert response.status_code == 200
            data = response.json()
            assert data["has_checkpoint"] is False
        finally:
            api_module.engine = orig
            api_module.app.dependency_overrides = {}

    def test_checkpoint_found(self):
        import opsswarm.api as api_module
        from opsswarm.models import RunRecord, RunState
        from opsswarm.evidence import EvidenceStore
        orig = api_module.engine
        try:
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
            api_module.app.dependency_overrides[api_module.verify_api_key] = lambda: "mock-key"
            client = TestClient(api_module.app)
            response = client.get("/runs/6/checkpoint", headers={"X-OpsSwarm-API-Key": "mock-key"})
            assert response.status_code == 200
            assert response.json()["has_checkpoint"] is True
        finally:
            api_module.engine = orig
            api_module.app.dependency_overrides = {}


class TestResumeEndpointWithData:
    def test_resume_no_checkpoint(self):
        import opsswarm.api as api_module
        from opsswarm.models import RunRecord, RunState
        from opsswarm.evidence import EvidenceStore
        orig = api_module.engine
        try:
            mock_run = RunRecord(run_id="r5", issue_number=7, state=RunState.INVESTIGATING)
            mock_ev = MagicMock(spec=EvidenceStore)
            mock_ev.get_last_checkpoint.return_value = None
            mock_engine = MagicMock()
            mock_engine.runs = {7: mock_run}
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)
            api_module.engine = mock_engine
            api_module.app.dependency_overrides[api_module.verify_api_key] = lambda: "mock-key"
            client = TestClient(api_module.app)
            response = client.post("/runs/7/resume", headers={"X-OpsSwarm-API-Key": "mock-key"})
            assert response.status_code == 400
        finally:
            api_module.engine = orig
            api_module.app.dependency_overrides = {}

    def test_resume_with_checkpoint(self):
        import opsswarm.api as api_module
        from opsswarm.models import RunRecord, RunState
        from opsswarm.evidence import EvidenceStore
        orig = api_module.engine
        try:
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
            api_module.app.dependency_overrides[api_module.verify_api_key] = lambda: "mock-key"
            client = TestClient(api_module.app)
            response = client.post("/runs/8/resume", headers={"X-OpsSwarm-API-Key": "mock-key"})
            assert response.status_code == 200
            data = response.json()
            assert data["resumed"] is True
            assert data["checkpoint_type"] == "HUMAN_GATE"
        finally:
            api_module.engine = orig
            api_module.app.dependency_overrides = {}


class TestMonitoringEndpoint:
    def test_monitoring_accepted(self):
        import opsswarm.api as api_module
        orig_engine = api_module.engine
        orig_gh = api_module.gh
        try:
            mock_ev = MagicMock()
            mock_gh = MagicMock()
            mock_gh.create_issue = AsyncMock(return_value={"number": 99})

            mock_engine = MagicMock()
            mock_engine.ev = mock_ev
            mock_engine.start_issue = AsyncMock(return_value=None)

            api_module.engine = mock_engine
            api_module.gh = mock_gh
            client = TestClient(api_module.app)

            with patch.dict(os.environ, {"OPSWARM_API_KEY": "mock-key"}):
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
                    headers={"X-OpsSwarm-API-Key": "mock-key"},
                )
            assert response.status_code == 200
            assert response.json()["accepted"] is True
            assert response.json()["issue_number"] == 99
        finally:
            api_module.engine = orig_engine
            api_module.gh = orig_gh
            api_module.app.dependency_overrides = {}
