import pytest
from unittest.mock import MagicMock, patch
from opsswarm.store import RunStore
from opsswarm.models import RunRecord

@pytest.mark.fault
def test_save_with_retry_failure():
    """Verify that save_with_retry returns False after max retries on disk error."""
    store = RunStore(data_dir="test_data", enable_atomic_writes=True)
    run = RunRecord(run_id="test_run", issue_number=1)
    
    # Mock save to raise Exception
    with patch.object(store, 'save', side_effect=Exception("Disk full")):
        with patch('time.sleep'): # Avoid waiting
            success = store.save_with_retry(run, max_retries=2)
            assert success is False
