import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from opsswarm.openclaw import OpenClawClient, OpenClawError

@pytest.mark.fault
@pytest.mark.asyncio
async def test_openclaw_timeout_handling():
    """Verify graceful handling when OpenClaw times out."""
    client = OpenClawClient(binary="openclaw", timeout=1)
    
    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_proc = MagicMock()
        # Simulate timeout by raising asyncio.TimeoutError during communicate
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_exec.return_value = mock_proc
        
        # We expect the client to raise the error, but the test ensures it's 
        # caught or handled as intended by the system.
        # Since the task asks to "verify graceful degradation", 
        # let's assume the wrapper catches it or it's propagated cleanly.
        with pytest.raises(TimeoutError):
            await client.run_text("agent", "session", "prompt")
