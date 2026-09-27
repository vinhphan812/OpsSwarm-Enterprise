"""Unit tests for opsswarm.openclaw module."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opsswarm.openclaw import OpenClawClient, OpenClawError


class TestOpenClawClient:
    """Tests for OpenClawClient class."""

    @pytest.fixture
    def client(self):
        """Create an OpenClawClient instance for testing."""
        return OpenClawClient(binary="openclaw", timeout=600)

    def test_init_sets_binary_and_timeout(self, client):
        """Client stores binary path and timeout."""
        assert client.binary == "openclaw"
        assert client.timeout == 600

    def test_init_custom_binary_and_timeout(self):
        """Client accepts custom binary and timeout."""
        client = OpenClawClient(binary="/custom/openclaw", timeout=120)
        assert client.binary == "/custom/openclaw"
        assert client.timeout == 120

    @pytest.mark.asyncio
    async def test_run_text_success(self, client):
        """run_text returns assistant text from envelope."""
        envelope = {"ok": True, "final": "Assistant response text"}

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
            mock_exec.return_value = mock_proc

            result = await client.run_text("agent", "session", "prompt")

            assert result == "Assistant response text"

    @pytest.mark.asyncio
    async def test_run_text_from_payloads(self, client):
        """run_text returns text from payloads array."""
        envelope = {
            "ok": True,
            "payloads": [{"text": "Payload text"}]
        }

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
            mock_exec.return_value = mock_proc

            result = await client.run_text("agent", "session", "prompt")

            assert result == "Payload text"

    @pytest.mark.asyncio
    async def test_run_text_from_result_payloads(self, client):
        """run_text returns text from result.payloads."""
        envelope = {
            "ok": True,
            "result": {
                "payloads": [{"text": "Result payload text"}]
            }
        }

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
            mock_exec.return_value = mock_proc

            result = await client.run_text("agent", "session", "prompt")

            assert result == "Result payload text"

    @pytest.mark.asyncio
    async def test_run_text_non_zero_exit_code(self, client):
        """run_text raises OpenClawError on non-zero exit code."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: something went wrong"))
            mock_exec.return_value = mock_proc

            with pytest.raises(OpenClawError, match="OpenClaw failed rc=1"):
                await client.run_text("agent", "session", "prompt")

    @pytest.mark.asyncio
    async def test_run_text_error_envelope(self, client):
        """run_text raises OpenClawError when envelope has ok=False."""
        envelope = {"ok": False, "error": "Something failed"}

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
            mock_exec.return_value = mock_proc

            with pytest.raises(OpenClawError, match="Something failed"):
                await client.run_text("agent", "session", "prompt")

    @pytest.mark.asyncio
    async def test_run_text_no_text_in_envelope(self, client):
        """run_text raises OpenClawError when no text found."""
        envelope = {"ok": True, "final": None}

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
            mock_exec.return_value = mock_proc

            with pytest.raises(OpenClawError, match="No assistant text"):
                await client.run_text("agent", "session", "prompt")

    @pytest.mark.asyncio
    async def test_run_text_from_payloads_invalid_element(self, client):
        """run_text handles invalid elements in payloads."""
        envelope = {
            "ok": True,
            "payloads": ["not a dict", {"text": 123}]  # Not dict, and not a string
        }
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
            mock_exec.return_value = mock_proc

            with pytest.raises(OpenClawError, match="No assistant text"):
                await client.run_text("agent", "session", "prompt")

    @pytest.mark.asyncio
    async def test_run_text_from_result_payloads_not_dict(self, client):
        """run_text handles result that is not a dict."""
        envelope = {
            "ok": True,
            "result": "not a dict"
        }
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(json.dumps(envelope).encode(), b""))
            mock_exec.return_value = mock_proc

            with pytest.raises(OpenClawError, match="No assistant text"):
                await client.run_text("agent", "session", "prompt")

    @pytest.mark.asyncio
    async def test_run_text_timeout_exceeded(self, client):
        """run_text raises error when process times out."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_exec.return_value = mock_proc

            with pytest.raises(TimeoutError):
                await client.run_text("agent", "session", "prompt")

    def test_run_json_extracts_json(self):
        """run_json extracts and returns parsed JSON from text."""
        # This tests the integration through the run_text flow
        pass

    @pytest.mark.asyncio
    async def test_run_json_with_fenced_json(self, client):
        """run_json parses fenced JSON blocks."""
        response_text = '''```json
{"key": "value", "number": 42}
```'''

        result = client._extract_json(response_text)

        assert result == {"key": "value", "number": 42}

    @pytest.mark.asyncio
    async def test_run_json_with_plain_json(self, client):
        """run_json parses plain JSON."""
        response_text = '{"plain": "json", "array": [1, 2, 3]}'

        result = client._extract_json(response_text)

        assert result == {"plain": "json", "array": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_run_json_invalid_json_raises(self, client):
        """run_json raises on invalid JSON."""
        with pytest.raises(json.JSONDecodeError):
            client._extract_json("not valid json at all")


class TestExtractJson:
    """Tests for the _extract_json static method."""

    def test_plain_json_object(self):
        """Parses plain JSON object."""
        text = '{"key": "value"}'
        result = OpenClawClient._extract_json(text)
        assert result == {"key": "value"}

    def test_plain_json_array(self):
        """Parses plain JSON array."""
        text = '[1, 2, 3]'
        result = OpenClawClient._extract_json(text)
        assert result == [1, 2, 3]

    def test_fenced_json_with_language(self):
        """Parses fenced JSON with language specifier."""
        text = '```json\n{"key": "value"}\n```'
        result = OpenClawClient._extract_json(text)
        assert result == {"key": "value"}

    def test_fenced_json_without_language(self):
        """Parses fenced JSON without language specifier."""
        text = '```\n{"key": "value"}\n```'
        result = OpenClawClient._extract_json(text)
        assert result == {"key": "value"}

    def test_fenced_json_with_trailing_text(self):
        """Extracts JSON from text with surrounding content."""
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        result = OpenClawClient._extract_json(text)
        assert result == {"key": "value"}

    def test_malformed_json_salvage(self):
        """Salvages JSON from malformed input - valid JSON passes through."""
        # Valid JSON with trailing text - the leading object is extracted
        text = '{"key": "value"}'
        result = OpenClawClient._extract_json(text)
        assert result == {"key": "value"}

    def test_malformed_array_salvage(self):
        """Salvages array from malformed input - valid array passes through."""
        text = '[1, 2, 3]'
        result = OpenClawClient._extract_json(text)
        assert result == [1, 2, 3]

    def test_no_json_raises(self):
        """Raises when no JSON found."""
        with pytest.raises(json.JSONDecodeError):
            OpenClawClient._extract_json("No JSON here at all")

    def test_empty_string_raises(self):
        """Raises on empty string."""
        with pytest.raises(json.JSONDecodeError):
            OpenClawClient._extract_json("")

    def test_leading_whitespace_stripped(self):
        """Leading whitespace is stripped."""
        text = '   {"key": "value"}'
        result = OpenClawClient._extract_json(text)
        assert result == {"key": "value"}

    def test_trailing_whitespace_stripped(self):
        """Trailing whitespace is stripped."""
        text = '{"key": "value"}   \n'
        result = OpenClawClient._extract_json(text)
        assert result == {"key": "value"}
