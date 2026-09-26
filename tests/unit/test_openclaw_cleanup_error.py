import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opsswarm.openclaw import OpenClawClient


@pytest.mark.asyncio
async def test_run_text_unlink_error():
    """run_text handles OSError during cleanup."""
    client = OpenClawClient()
    envelope = {"ok": True, "final": "Assistant response text"}

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec, \
            patch("os.unlink", side_effect=OSError("Cleanup failed")):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
        mock_exec.return_value = mock_proc

        result = await client.run_text("agent", "session", "prompt")
        assert result == "Assistant response text"
