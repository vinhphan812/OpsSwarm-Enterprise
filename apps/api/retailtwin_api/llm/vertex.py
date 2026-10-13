"""Native Vertex Gemini adapter authenticated with Application Default Credentials.

Cloud Run provides ADC from the revision service account; the adapter never uses
service-account key files. Locally run ``gcloud auth application-default login``.
The integration test mocks ADC and HTTP transport, proving the REST request and
response code path without credentials or a billable model invocation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast

import httpx

from .contracts import (
    AuthenticationError,
    InvalidStructuredOutputError,
    LlmMessage,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    LlmTool,
    LlmToolCall,
    ProviderError,
    RateLimitError,
    RequestTimeout,
    StructuredOutput,
    TokenUsage,
    ToolCallError,
)

_logger = logging.getLogger(__name__)

# Vertex AI REST API endpoint base
_VERTEX_API_BASE = "https://{location}-aiplatform.googleapis.com/v1"

# Vertex's generateContent REST endpoint requires an OAuth 2.0 token obtained
# from ADC. Cloud Run supplies it from the revision service account; local users
# create it with `gcloud auth application-default login`. No key files are read.
_VERTEX_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Retry configuration
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0


def _backoff(attempt: int) -> float:
    """Exponential back-off with jitter cap at 32 s."""
    return cast(float, min(float(_INITIAL_BACKOFF) * (2 ** attempt), 32.0))


def _vertex_error_to_exception(status_code: int, payload: dict[str, Any]) -> ProviderError:
    """Map Vertex AI error responses to the appropriate typed exception."""
    error_msg = payload.get("error", {}).get("message", str(payload))
    code = payload.get("error", {}).get("code", 0)
    if status_code == 401 or code == "UNAUTHENTICATED":
        return AuthenticationError(error_msg)
    if status_code == 403 or code == "PERMISSION_DENIED":
        return AuthenticationError(f"Permission denied: {error_msg}")
    if status_code == 429 or code == "RESOURCE_EXHAUSTED":
        return RateLimitError(error_msg)
    if status_code == 400 and (
        "function_declaration" in error_msg.lower()
        or "schema" in error_msg.lower()
        or "structured" in error_msg.lower()
    ):
        return InvalidStructuredOutputError(error_msg)
    return ProviderError(error_msg, retryable=status_code >= 500)


def _convert_tools_vertex(tools: list[LlmTool]) -> list[dict[str, Any]]:
    """Convert neutral tools to Vertex's native functionDeclarations shape."""
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        }
        for tool in tools
    ]


def _normalize_vertex_tool_calls(
    candidates: list[dict[str, Any]],
) -> tuple[list[LlmToolCall], str | None]:
    """Extract tool calls from Vertex candidates; return (tool_calls, finish_reason)."""
    tool_calls: list[LlmToolCall] = []
    finish_reason: str | None = None

    for candidate in candidates:
        finish_reason = candidate.get("finishReason", "OTHER")
        content_parts = candidate.get("content", {}).get("parts", [])
        for part in content_parts:
            fc = part.get("functionCall")
            if fc:
                args_raw = fc.get("args", {})
                if isinstance(args_raw, str):
                    try:
                        args: dict[str, Any] = json.loads(args_raw)
                    except json.JSONDecodeError:
                        raise ToolCallError(
                            f"Malformed function_call arguments for '{fc.get('name')}': not valid JSON"
                        )
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    raise ToolCallError(
                        f"Unexpected function_call arguments type for '{fc.get('name')}'"
                    )
                tool_calls.append(
                    LlmToolCall(
                        id=fc.get("id", ""),
                        name=fc["name"],
                        arguments=args,
                    )
                )

    return tool_calls, finish_reason


def _vertex_content_to_text(candidates: list[dict[str, Any]]) -> str | None:
    """Extract text content from Vertex candidates."""
    parts: list[str] = []
    for candidate in candidates:
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if text:
                parts.append(text)
    return "\n".join(parts) or None


class VertexProvider(LlmProvider):
    """Vertex AI Gemini adapter using ADC.

    Supports:
      - Text completions
      - Tool-calling (function_declarations)
      - Structured output (response_schema)
      - Bounded retry with exponential back-off for rate-limit and 5xx errors
    """

    def __init__(
        self,
        project_id: str,
        location: str,
        model: str,
        timeout: float,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.model = model
        self.timeout = timeout
        self._endpoint = (
            f"{_VERTEX_API_BASE.format(location=location)}"
            f"/projects/{project_id}/locations/{location}"
            f"/publishers/google/models/{model}:generateContent"
        )

    def _get_adc_access_token(self) -> str:
        """Resolve and refresh ADC from Cloud Run or local gcloud authentication."""
        try:
            if TYPE_CHECKING:
                from google.auth.transport.requests import Request as _RequestTyping

            import google.auth
            from google.auth.transport.requests import Request

            credentials, _ = google.auth.default(scopes=[_VERTEX_SCOPE])
            if not credentials.valid or not credentials.token:
                credentials.refresh(Request())
            if not credentials.token:
                raise AuthenticationError("ADC did not supply an access token")
            return str(credentials.token)
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(
                "Unable to obtain Google Application Default Credentials for Vertex AI"
            ) from exc

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Call Vertex with bounded retries and normalized output."""
        payload = self._build_payload(request)
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._do_request(payload, request)
                # Local schema validation — explicit failure on non-conformant output
                if request.structured_output:
                    response.validate_structured_output(request.structured_output.json_schema)
                return response
            except RateLimitError as exc:
                last_exc = exc
            except (AuthenticationError, InvalidStructuredOutputError, ToolCallError, RequestTimeout):
                raise
            except ProviderError as exc:
                if not exc.retryable or attempt == _MAX_RETRIES - 1:
                    raise
                last_exc = exc
            backoff_secs = _backoff(attempt)
            _logger.warning(
                "Vertex retryable failure %d/%d; sleeping %.1f s",
                attempt + 1,
                _MAX_RETRIES,
                backoff_secs,
            )
            await asyncio.sleep(backoff_secs)
        raise last_exc or ProviderError("Vertex inference failed after all retries.")

    async def _do_request(
        self,
        payload: dict[str, Any],
        request: LlmRequest,
    ) -> LlmResponse:
        headers = {
            "Authorization": f"Bearer {self._get_adc_access_token()}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    self._endpoint,
                    headers=headers,
                    json=payload,
                )
            except httpx.TimeoutException:
                raise RequestTimeout()
            except httpx.HTTPError as e:
                raise ProviderError(str(e))

        if not response.is_success:
            try:
                error_payload_json = response.json()
            except Exception:
                error_payload_json = {}
            exc = _vertex_error_to_exception(response.status_code, error_payload_json)
            raise exc

        data = response.json()
        return self._parse_response(data, request.structured_output)

    def _build_payload(self, request: LlmRequest) -> dict[str, Any]:
        system_messages = [message for message in request.messages if message.role == "system"]
        payload: dict[str, Any] = {
            "contents": [
                _message_to_vertex(message)
                for message in request.messages
                if message.role != "system"
            ]
        }
        if system_messages:
            payload["systemInstruction"] = {
                "parts": [{"text": message.content or ""} for message in system_messages]
            }

        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.structured_output:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = request.structured_output.json_schema
        if generation_config:
            payload["generationConfig"] = generation_config

        if request.tools:
            payload["tools"] = [{"functionDeclarations": _convert_tools_vertex(request.tools)}]

        return payload

    def _parse_response(
        self,
        data: dict[str, Any],
        structured_output: StructuredOutput | None,
    ) -> LlmResponse:
        candidates = data.get("candidates", [])
        if not candidates:
            error_detail = data.get("error", {}).get("message", "No candidates returned")
            raise ProviderError(error_detail)

        content = _vertex_content_to_text(candidates)
        tool_calls, finish_reason = _normalize_vertex_tool_calls(candidates)

        if structured_output and content is not None:
            try:
                content = json.dumps(json.loads(content), separators=(",", ":"), ensure_ascii=False)
            except json.JSONDecodeError as exc:
                raise InvalidStructuredOutputError(
                    "Model returned invalid JSON for structured output"
                ) from exc
        elif structured_output and not tool_calls:
            raise InvalidStructuredOutputError(
                "Model returned neither JSON nor a structured function response"
            )

        usage_data = data.get("usageMetadata", data.get("usage", {}))
        if not isinstance(usage_data, dict):
            usage_data = {}
        usage = TokenUsage(
            prompt_tokens=usage_data.get("promptTokenCount", usage_data.get("promptTokens", 0)),
            completion_tokens=usage_data.get("candidatesTokenCount", usage_data.get("candidatesTokens", 0)),
            total_tokens=usage_data.get("totalTokenCount", usage_data.get("totalTokens", 0)),
        )

        return LlmResponse(
            id=data.get("responseId", data.get("modelVersion", self.model)),
            model=data.get("modelVersion", self.model),
            content=content,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            usage=usage,
            raw=data,
        )


def _message_to_vertex(message: LlmMessage) -> dict[str, Any]:
    """Convert a neutral message to native Gemini content parts."""
    if message.role == "tool":
        return {
            "role": "user",
            "parts": [{"functionResponse": {
                "name": message.name or "unknown",
                "response": {"result": message.content or ""},
            }}],
        }
    if message.tool_call_id:
        return {
            "role": "model",
            "parts": [{"functionCall": {
                "id": message.tool_call_id,
                "name": message.name,
                "args": message.content or "{}",
            }}],
        }
    return {
        "role": "model" if message.role == "assistant" else "user",
        "parts": [{"text": message.content or ""}],
    }
