import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from opsswarm.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
def clean_test_data(tmp_path, monkeypatch):
    """Point orchestrator at a clean tmp data dir so stale .jsonl doesn't poison chain verification."""
    from pathlib import Path
    d = tmp_path / "test_concurrency"
    d.mkdir()
    monkeypatch.setenv("OPSWARM_DATA_DIR", str(d))
    yield
    # No cleanup needed — tmp_path is removed after test

@pytest.mark.fault
@pytest.mark.asyncio
async def test_concurrent_webhooks():
    """Verify no race condition on concurrent webhook delivery via locks."""
    cfg = {"labels": {"base": []}, "openclaw": {"profiles": {"incident-manager": "manager"}}}
    gh = AsyncMock()
    oc = AsyncMock()
    
    # Mock get_issue to be slow
    async def slow_get_issue(number):
        await asyncio.sleep(0.1)
        return {"number": number, "labels": [{"name": "opsswarm"}]}
    gh.get_issue.side_effect = slow_get_issue
    
    # Orchestrator starts with recovery DISABLED so stale .jsonl from prior tests doesn't
    # trigger MalformedEvidenceError during the chain-verification pass in _recover_runs().
    # Recovery is tested in dedicated recovery tests; this test focuses on concurrency.
    engine = Orchestrator(cfg, gh, oc, data_dir="test_data_concurrency", enable_recovery=False)
    oc.run_json.return_value = {"tasks": []}
    
    # Simultaneous start_issue calls
    results = await asyncio.gather(
        engine.start_issue(1, delivery_id="del1"),
        engine.start_issue(1, delivery_id="del2") # Should be skipped due to idempotency
    )
    
    # Verify engine only created one run for issue 1
    assert len(engine.runs) == 1
    assert results[0].run_id == results[1].run_id
