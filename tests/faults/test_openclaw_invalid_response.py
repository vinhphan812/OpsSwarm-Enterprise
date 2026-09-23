import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from opsswarm.openclaw import OpenClawClient, OpenClawError

@pytest.mark.fault
@pytest.mark.asyncio
async def test_openclaw_invalid_response_handling():
    """Verify handling of malformed JSON from OpenClaw."""
    client = OpenClawClient(binary="openclaw")
    
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        # Malformed JSON
        mock_proc.communicate = AsyncMock(return_value=(b"{ invalid json ", b""))
        mock_exec.return_value = mock_proc
        
        # Depending on implementation, this might raise JSONDecodeError or a custom error
        with pytest.raises(json.JSONDecodeError):
            await client.run_text("agent", "session", "prompt")
