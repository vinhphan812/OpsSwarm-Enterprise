"""OpenAI-compatible adapter.

Supports any OpenAI-API-compatible endpoint (OpenAI, Azure OpenAI, local proxies,
etc.) via the configurable base_url.  Credentials are read from the API key passed
to the provider constructor; no defaults are applied.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

import httpx

from .contracts import (
    AuthenticationError,
    InvalidStructuredOutputError,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    LlmToolCall,
    ProviderError,
    RateLimitError,
    RequestTimeout,
    ToolCallError,
    TokenUsage,
)

_logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_INITIAL_BACKOFF: float = 1.0  # seconds


def _backoff(attempt: int) -> float:
    """Exponential back-off capped at 32 s."""
    return min(float(_INITIAL_BACKOFF) * float(2 ** attempt), 32.0)


def _http_error_to_exception(status_code: int, body: dict[str, Any]) -> ProviderError:
    """Map HTTP status + error body to the most specific typed exception."""
    err = body.get("error", {})
    message = err.get("message", str(body))

    if status_code == 401:
        return AuthenticationError(message)
    if status_code == 403:
        return AuthenticationError(f"Forbidden: {message}")
    if status_code == 429:
        return RateLimitError(message)
    if status_code == 400 and (
        "function_declaration" in message.lower()
        or "schema" in message.lower()
        or "structured_output" in message.lower()
        or "json_schema" in message.lower()
    ):
        return InvalidStructuredOutputError(message)
    return ProviderError(message, retryable=status_code >= 500)


def _convert_tools_openai(tools: list[Any]) -> list[dict[str, Any]]:

    """Convert LlmTool list to OpenAI tool definitions format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _safe_parse_tool_call(tc: dict[str, Any]) -> LlmToolCall:
    """Parse one tool_call entry, normalising the arguments field.

    OpenAI returns ``function.arguments`` as a JSON *string*.  Other providers
    (e.g. local models) may return a dict directly.  Both are handled.
    """
    func = tc.get("function", {})
    name = func.get("name", "")
    if not name:
        raise ToolCallError("tool_call is missing a function name")

    raw_args = func.get("arguments", {})
    if isinstance(raw_args, str):
        try:
            args: dict[str, Any] = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise ToolCallError(
                f"tool_call '{name}' has malformed arguments: {exc}"
            )
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        raise ToolCallError(
            f"tool_call '{name}' has unexpected arguments type: {type(raw_args).__name__}"
        )

    return LlmToolCall(
        id=tc.get("id", ""),
        name=name,
        arguments=args,
    )


class OpenAiCompatibleProvider(LlmProvider):
    """OpenAI-API-compatible inference adapter.

    The ``base_url`` must be provided by the caller (never hard-coded).
    All retryable failures (rate-limit, 5xx) are retried with exponential back-off.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Send a completion request with bounded retry."""
        payload = self._build_payload(request)
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._do_request(payload)
                # Local schema validation — explicit failure on non-conformant output
                if request.structured_output:
                    response.validate_structured_output(request.structured_output.json_schema)
                return response
            except RateLimitError as exc:
                last_exc = exc
                await asyncio.sleep(_backoff(attempt))
                _logger.warning(
                    "OpenAI rate-limit attempt %d/%d -- retrying after %.1f s",
                    attempt + 1, _MAX_RETRIES, _backoff(attempt),
                )
            except AuthenticationError:
                raise  # Never retry auth failures
            except InvalidStructuredOutputError:
                raise  # Never retry output errors
            except ToolCallError:
                raise  # Never retry malformed tool calls
            except RequestTimeout:
                raise
            except ProviderError as exc:
                if exc.retryable and attempt < _MAX_RETRIES - 1:
                    last_exc = exc
                    await asyncio.sleep(_backoff(attempt))
                    _logger.warning(
                        "OpenAI retryable error attempt %d/%d -- retrying after %.1f s: %s",
                        attempt + 1, _MAX_RETRIES, _backoff(attempt), exc.message,
                    )
                else:
                    raise

        raise last_exc or ProviderError("OpenAI inference failed after all retries.")

    async def _do_request(self, payload: dict[str, Any]) -> LlmResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
            except httpx.TimeoutException:
                raise RequestTimeout()
            except httpx.HTTPError as e:
                raise ProviderError(str(e))

        if not response.is_success:
            try:
                body = response.json()
            except Exception:
                body = {}
            exc = _http_error_to_exception(response.status_code, body)
            raise exc

        return self._parse_response(response.json())

    def _build_payload(self, request: LlmRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": [m.model_dump() for m in request.messages],
        }

        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        # Canonical tool definitions
        if request.tools:
            payload["tools"] = _convert_tools_openai(request.tools)

        # Tool-choice policy
        if request.tool_choice and request.tools:
            policy = request.tool_choice
            if policy.mode == "none":
                payload["tool_choice"] = "none"
            elif policy.mode == "required_tool":
                payload["tool_choice"] = {
                    "type": "function",
                    "function": {"name": policy.name or request.tools[0].name},
                }
            elif policy.mode == "tool_choice":
                if policy.name:
                    payload["tool_choice"] = {
                        "type": "function",
                        "function": {"name": policy.name},
                    }
                else:
                    payload["tool_choice"] = "auto"

        # Structured output — send as response_format with JSON schema
        if request.structured_output:
            so = request.structured_output
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": so.name,
                    "schema": so.json_schema,  # Pydantic field name; alias='schema' is the JSON key
                    "strict": so.strict,
                },
            }

        return payload

    def _parse_response(self, data: dict[str, Any]) -> LlmResponse:
        choices = data.get("choices", [])
        if not choices:
            raise ProviderError("No choices returned in response")

        choice = choices[0]
        message = choice.get("message", {})

        # Parse tool calls safely
        tool_calls: list[LlmToolCall] = []
        raw_tcs = message.get("tool_calls", [])
        for raw_tc in raw_tcs:
            try:
                tool_calls.append(_safe_parse_tool_call(raw_tc))
            except ToolCallError:
                raise  # Propagate malformed tool calls immediately

        # Guard: tools were requested but none returned
        if not tool_calls and raw_tcs:
            raise ToolCallError("Some tool_calls were returned but could not be parsed")

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return LlmResponse(
            id=data.get("id", "unknown"),
            model=data.get("model", self.model),
            content=message.get("content"),
            finish_reason=choice.get("finish_reason"),
            tool_calls=tool_calls,
            usage=usage,
            raw=data,
        )
