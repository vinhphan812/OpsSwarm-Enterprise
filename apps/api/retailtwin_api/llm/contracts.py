"""Provider-neutral contracts for model inference."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# jsonschema is bundled with pydantic>=2.9 via pydantic's own dependency
import jsonschema as _jsonschema


class LlmTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class StructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    json_schema: dict[str, Any] = Field(alias="schema")
    strict: bool = True


class ToolChoicePolicy(BaseModel):
    """Tool-choice policy — mirrors the OpenAI tool_choice modes.

    ``required_tool``: the model MUST call a tool (raises InvalidToolChoiceError
    if it does not).  ``tool_choice``: the model may call a tool of its choosing.
    ``none``: no tool calls are requested (LlmRequest.tools should be empty).
    """

    mode: Literal["required_tool", "tool_choice", "none"] = "tool_choice"
    name: str | None = None  # restrict to a specific tool name when mode is "tool_choice"

    def validate_for_request(self, tools: list[LlmTool]) -> None:
        if self.mode == "none" and tools:
            raise ValueError(
                "tool_choice policy 'none' is invalid when tools are registered"
            )
        if self.mode == "tool_choice" and self.name is not None:
            if not any(t.name == self.name for t in tools):
                raise ValueError(
                    f"tool_choice 'name={self.name}' is not in the registered tools"
                )


class LlmMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_call_id: str | None = None
    name: str | None = None


class LlmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    messages: list[LlmMessage] = Field(min_length=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    tools: list[LlmTool] = Field(default_factory=list)
    tool_choice: ToolChoicePolicy | None = None
    structured_output: StructuredOutput | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LlmToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any]


class LlmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    model: str
    content: str | None = None
    finish_reason: str | None = None
    tool_calls: list[LlmToolCall] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    raw: dict[str, Any] = Field(default_factory=dict)

    def validate_structured_output(self, schema: dict[str, Any]) -> None:
        """Validate self.content against the requested JSON schema.

        Raises InvalidStructuredOutputError if self.content is not valid JSON
        or does not conform to ``schema``.
        """
        import json as _json

        if self.content is None:
            raise InvalidStructuredOutputError(
                "structured output was requested but the model returned no content"
            )
        try:
            parsed: dict[str, Any] = _json.loads(self.content)
        except _json.JSONDecodeError as exc:
            raise InvalidStructuredOutputError(
                f"structured output is not valid JSON: {exc}"
            ) from exc
        try:
            _jsonschema.validate(instance=parsed, schema=schema)
        except _jsonschema.ValidationError as exc:
            raise InvalidStructuredOutputError(
                f"structured output does not conform to requested schema: {exc.message}"
            ) from exc


class LlmError(Exception):
    """Normalized, safe inference error; provider payloads are not exposed."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class ConfigurationError(LlmError):
    def __init__(self, message: str) -> None:
        super().__init__("configuration_error", message)


class ProviderError(LlmError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__("provider_error", message, retryable=retryable)


class AuthenticationError(ProviderError):
    """Raised when the API key or credential is invalid, missing, or expired."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class RateLimitError(ProviderError):
    """Raised when the provider throttles the request; safe to retry after back-off."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class InvalidStructuredOutputError(ProviderError):
    """Raised when the model refuses or cannot produce the requested structured output."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ToolCallError(ProviderError):
    """Raised when a tool-call response is malformed, unknown, or the tool result is missing."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)


class RequestTimeout(LlmError):
    def __init__(self) -> None:
        super().__init__("timeout", "The model request timed out.", retryable=True)


class RequestCancelled(LlmError):
    def __init__(self) -> None:
        super().__init__("cancelled", "The model request was cancelled.")


class LlmTransportError(Exception):
    """Internal transport failure, normalized by an adapter."""


class LlmTransportResponse(BaseModel):
    status_code: int
    payload: dict[str, Any] = Field(default_factory=dict)


class LlmProvider:
    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise NotImplementedError
