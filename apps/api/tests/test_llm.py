"""Tests for the provider-neutral LLM contracts and adapters."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from retailtwin_api.llm.contracts import (
    AuthenticationError,
    ConfigurationError,
    InvalidStructuredOutputError,
    LlmError,
    LlmMessage,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    LlmTool,
    LlmToolCall,
    ProviderError,
    RateLimitError,
    RequestCancelled,
    RequestTimeout,
    StructuredOutput,
    ToolCallError,
    ToolChoicePolicy,
)
from retailtwin_api.llm.factory import LlmConfig, create_provider
from retailtwin_api.llm.openai_compatible import (
    OpenAiCompatibleProvider,
    _convert_tools_openai,
    _safe_parse_tool_call,
)
from retailtwin_api.llm.vertex import VertexProvider


@pytest.fixture(autouse=True)
def mock_vertex_adc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep adapter tests offline; dedicated tests assert the Bearer header."""
    monkeypatch.setattr(VertexProvider, "_get_adc_access_token", lambda self: "test-adc-token")


# ─── Mock helpers ───────────────────────────────────────────────────────────────


class MockResponse:
    """Minimal successful OpenAI-compatible response."""

    def __init__(self, data: dict[str, object], status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, object]:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")


class MockClient:
    """Async httpx client replacement with observable request data."""

    def __init__(self, response: MockResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def __aenter__(self) -> "MockClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> MockResponse:
        self.calls.append((args, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


# ─── Helpers ───────────────────────────────────────────────────────────────────


def make_request(
    model: str = "gpt-4",
    messages: list[LlmMessage] | None = None,
    tools: list[LlmTool] | None = None,
    structured_output: StructuredOutput | None = None,
    tool_choice: ToolChoicePolicy | None = None,
) -> LlmRequest:
    return LlmRequest(
        model=model,
        messages=messages or [LlmMessage(role="user", content="Hi")],
        tools=tools or [],
        structured_output=structured_output,
        tool_choice=tool_choice,
    )


# ─── OpenAI adapter ────────────────────────────────────────────────────────────


def test_openai_adapter_success_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [{
                "message": {"content": "Hello!"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = create_provider(
        LlmConfig(
            provider="openai_compatible",
            model="gpt-4",
            api_key="test-key",
            base_url="https://example.test/v1/",
        )
    )

    response = asyncio.run(provider.complete(make_request()))

    assert isinstance(provider, OpenAiCompatibleProvider)
    assert response.content == "Hello!"
    assert response.usage.total_tokens == 2
    assert client.calls[0][0] == ("https://example.test/v1/chat/completions",)
    assert client.calls[0][1]["headers"] == {"Authorization": "Bearer test-key", "Content-Type": "application/json"}


def test_openai_adapter_sends_tool_definitions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-124",
            "model": "gpt-4",
            "choices": [{
                "message": {"content": None, "tool_calls": [
                    {
                        "id": "call_abc",
                        "function": {
                            "name": "get_inventory",
                            "arguments": json.dumps({"sku": "P017"}),
                        },
                    }
                ]},
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory", description="Get inventory", parameters={"type": "object", "properties": {"sku": {"type": "string"}}})]
    response = asyncio.run(provider.complete(make_request(tools=tools)))

    sent_payload = client.calls[0][1]["json"]
    assert "tools" in sent_payload
    assert sent_payload["tools"][0]["type"] == "function"
    assert sent_payload["tools"][0]["function"]["name"] == "get_inventory"
    assert response.tool_calls[0].name == "get_inventory"
    assert response.tool_calls[0].arguments == {"sku": "P017"}


def test_openai_adapter_sends_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-125",
            "model": "gpt-4",
            "choices": [{
                "message": {"content": '{"decision":"buy","quantity":5}'},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    so = StructuredOutput(name="Decision", schema={"type": "object", "properties": {"decision": {"type": "string"}}})
    response = asyncio.run(provider.complete(make_request(structured_output=so)))

    sent_payload = client.calls[0][1]["json"]
    assert "response_format" in sent_payload
    assert sent_payload["response_format"]["type"] == "json_schema"
    assert sent_payload["response_format"]["json_schema"]["name"] == "Decision"
    assert response.content is not None


def test_openai_adapter_safe_json_parse_string_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI returns function.arguments as a JSON string — must be parsed."""
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-126",
            "model": "gpt-4",
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_xyz",
                        "function": {
                            "name": "order_item",
                            "arguments": '{"item_id": "ABC", "qty": 3}',  # string, not dict
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    response = asyncio.run(provider.complete(make_request()))

    assert response.tool_calls[0].arguments == {"item_id": "ABC", "qty": 3}


def test_openai_adapter_safe_json_parse_dict_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some providers return function.arguments as a dict directly."""
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-127",
            "model": "gpt-4",
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_dict",
                        "function": {
                            "name": "get_store_state",
                            "arguments": {"store_id": "S001"},  # dict, not string
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    response = asyncio.run(provider.complete(make_request()))

    assert response.tool_calls[0].arguments == {"store_id": "S001"}


def test_openai_adapter_malformed_arguments_raises_tool_call_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-128",
            "model": "gpt-4",
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call_bad",
                        "function": {
                            "name": "bad_tool",
                            "arguments": "not valid json {{{",
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )

    with pytest.raises(ToolCallError, match="malformed arguments"):
        asyncio.run(provider.complete(make_request()))


def test_openai_adapter_normalizes_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(httpx.TimeoutException("timed out"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=1,
    )

    with pytest.raises(RequestTimeout) as error:
        asyncio.run(provider.complete(make_request()))

    assert error.value.retryable is True


def test_openai_adapter_normalizes_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(httpx.ConnectError("unavailable"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=1,
    )

    with pytest.raises(ProviderError, match="unavailable"):
        asyncio.run(provider.complete(make_request()))


def test_openai_adapter_maps_401_to_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({"error": {"message": "Invalid API key"}}, status_code=401)
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="bad-key",
        model="gpt-4",
        timeout=30,
    )

    with pytest.raises(AuthenticationError):
        asyncio.run(provider.complete(make_request()))


def test_openai_adapter_maps_429_to_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({"error": {"message": "Rate limit exceeded"}}, status_code=429)
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )

    with pytest.raises(RateLimitError):
        asyncio.run(provider.complete(make_request()))


# ─── Vertex adapter ────────────────────────────────────────────────────────────


def test_vertex_requires_project_id() -> None:
    with pytest.raises(ConfigurationError, match="project_id"):
        create_provider(LlmConfig(provider="vertex_gemini", model="gemini-2.5-flash"))


def test_vertex_builds_correct_endpoint() -> None:
    provider = VertexProvider(
        project_id="my-project",
        location="us-central1",
        model="gemini-2.0-flash",
        timeout=30,
    )
    assert "my-project" in provider._endpoint
    assert "us-central1" in provider._endpoint
    assert "gemini-2.0-flash" in provider._endpoint
    assert provider._endpoint.startswith("https://us-central1-aiplatform.googleapis.com")


def test_vertex_maps_401_to_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({"error": {"message": "UNAUTHENTICATED"}}, status_code=401)
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = VertexProvider(
        project_id="my-project",
        location="us-central1",
        model="gemini-2.0-flash",
        timeout=30,
    )

    with pytest.raises(AuthenticationError):
        asyncio.run(provider.complete(make_request(model="gemini-2.0-flash")))


def test_vertex_maps_429_to_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({"error": {"message": "Resource exhausted"}}, status_code=429)
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = VertexProvider(
        project_id="my-project",
        location="us-central1",
        model="gemini-2.0-flash",
        timeout=30,
    )

    with pytest.raises(RateLimitError):
        asyncio.run(provider.complete(make_request(model="gemini-2.0-flash")))


def test_vertex_sends_tool_definitions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "candidates": [{
                "content": {
                    "parts": [{"text": "Inventory fetched."}]
                },
                "finishReason": "STOP",
            }],
            "usage": {"promptTokens": 5, "candidatesTokens": 3, "totalTokens": 8},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = VertexProvider(
        project_id="my-project",
        location="us-central1",
        model="gemini-2.0-flash",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory", description="Get stock", parameters={"type": "object", "properties": {"sku": {"type": "string"}}})]
    asyncio.run(provider.complete(make_request(model="gemini-2.0-flash", tools=tools)))

    sent_payload = client.calls[0][1]["json"]
    assert "tools" in sent_payload
    assert sent_payload["tools"][0]["functionDeclarations"][0]["name"] == "get_inventory"


def test_vertex_sends_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "candidates": [{
                "content": {
                    "parts": [{"text": '{"decision":"buy","quantity":2}'}]  # text, not functionCall
                },
                "finishReason": "STOP",
            }],
            "usage": {"promptTokens": 5, "candidatesTokens": 3, "totalTokens": 8},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = VertexProvider(
        project_id="my-project",
        location="us-central1",
        model="gemini-2.0-flash",
        timeout=30,
    )
    so = StructuredOutput(name="Decision", schema={"type": "object", "properties": {"decision": {"type": "string"}}})
    asyncio.run(provider.complete(make_request(model="gemini-2.0-flash", structured_output=so)))

    sent_payload = client.calls[0][1]["json"]
    assert sent_payload["generationConfig"]["responseMimeType"] == "application/json"
    assert sent_payload["generationConfig"]["responseSchema"] == so.json_schema


def test_vertex_normalizes_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "candidates": [{
                "content": {
                    "parts": [{
                        "functionCall": {
                            "name": "get_inventory",
                            "args": {"sku": "P017"},
                        }
                    }]
                },
                "finishReason": "STOP",
            }],
            "usage": {"promptTokens": 5, "candidatesTokens": 3, "totalTokens": 8},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = VertexProvider(
        project_id="my-project",
        location="us-central1",
        model="gemini-2.0-flash",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory")]
    response = asyncio.run(provider.complete(make_request(model="gemini-2.0-flash", tools=tools)))

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "get_inventory"
    assert response.tool_calls[0].arguments == {"sku": "P017"}


def test_vertex_complete_uses_adc_authorized_rest_request_and_normalizes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock transport proves the full Cloud Run/ADC REST contract without secrets."""
    client = MockClient(
        MockResponse({
            "responseId": "response-123",
            "modelVersion": "gemini-2.0-flash",
            "candidates": [{
                "content": {"parts": [{"text": "Inventory fetched."}]},
                "finishReason": "STOP",
            }],
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 3,
                "totalTokenCount": 8,
            },
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(VertexProvider, "_get_adc_access_token", lambda self: "adc-access-token")
    provider = VertexProvider("my-project", "us-central1", "gemini-2.0-flash", 30)

    response = asyncio.run(provider.complete(make_request(model="gemini-2.0-flash")))

    assert response.id == "response-123"
    assert response.content == "Inventory fetched."
    assert response.usage.model_dump() == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
    }
    assert client.calls == [(
        (
            "https://us-central1-aiplatform.googleapis.com/v1/projects/my-project/"
            "locations/us-central1/publishers/google/models/gemini-2.0-flash:generateContent",
        ),
        {
            "headers": {
                "Authorization": "Bearer adc-access-token",
                "Content-Type": "application/json",
            },
            "json": {"contents": [{"role": "user", "parts": [{"text": "Hi"}]}]},
        },
    )]


def test_vertex_structured_output_normalizes_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "candidates": [{
                "content": {"parts": [{"text": '{ "decision": "buy", "quantity": 2 }'}]},
                "finishReason": "STOP",
            }],
            "usageMetadata": {},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(VertexProvider, "_get_adc_access_token", lambda self: "adc-access-token")
    provider = VertexProvider("my-project", "us-central1", "gemini-2.0-flash", 30)
    so = StructuredOutput(
        name="Decision",
        schema={"type": "object", "properties": {"decision": {"type": "string"}}},
    )

    response = asyncio.run(provider.complete(make_request(model="gemini-2.0-flash", structured_output=so)))

    assert response.content == '{"decision":"buy","quantity":2}'
    assert response.finish_reason == "STOP"
    sent_payload = client.calls[0][1]["json"]
    assert sent_payload["generationConfig"] == {
        "responseMimeType": "application/json",
        "responseSchema": so.json_schema,
    }


def test_vertex_malformed_tool_args_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vertex functionCall.args that is neither dict nor JSON-string raises ToolCallError."""
    client = MockClient(
        MockResponse({
            "candidates": [{
                "content": {
                    "parts": [{
                        "functionCall": {
                            "name": "bad_tool",
                            "args": "not-a-dict-or-string",
                        }
                    }]
                },
                "finishReason": "STOP",
            }],
            "usage": {"promptTokens": 1, "candidatesTokens": 1, "totalTokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = VertexProvider(
        project_id="my-project",
        location="us-central1",
        model="gemini-2.0-flash",
        timeout=30,
    )
    # Tools must be present in the request for tool-call parsing to trigger
    tools = [LlmTool(name="bad_tool")]

    with pytest.raises(ToolCallError):
        asyncio.run(provider.complete(make_request(model="gemini-2.0-flash", tools=tools)))


# ─── LLM_BASE_URL configuration ───────────────────────────────────────────────


def test_openai_requires_base_url_or_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(ConfigurationError, match="LLM_BASE_URL"):
        create_provider(LlmConfig(provider="openai_compatible", model="gpt-4", api_key="key"))


def test_openai_uses_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://my-endpoint.example/v1")
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-env",
            "model": "gpt-4",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    provider = create_provider(LlmConfig(provider="openai_compatible", model="gpt-4", api_key="key"))

    asyncio.run(provider.complete(make_request()))
    assert client.calls[0][0] == ("https://my-endpoint.example/v1/chat/completions",)


def test_openai_explicit_base_url_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://env-url.example/v1")
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-explicit",
            "model": "gpt-4",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)

    provider = create_provider(
        LlmConfig(provider="openai_compatible", model="gpt-4", api_key="key", base_url="https://explicit.example/v1")
    )

    asyncio.run(provider.complete(make_request()))
    assert client.calls[0][0] == ("https://explicit.example/v1/chat/completions",)


# ─── Config validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [
        {"provider": "openai_compatible", "model": ""},
        {"provider": "openai_compatible", "model": "gpt-4", "timeout": 0},
    ],
)
def test_config_rejects_invalid_values(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LlmConfig.model_validate(config)


# ─── contracts: LlmTool ───────────────────────────────────────────────────────


def test_llm_tool_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LlmTool.model_validate(
            {"name": "test_tool", "description": None, "unknown_field": True}
        )


def test_llm_tool_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        LlmTool.model_validate({"name": ""})


def test_llm_tool_minimal_valid() -> None:
    tool = LlmTool(name="get_store_state")
    assert tool.name == "get_store_state"
    assert tool.description is None


# ─── contracts: StructuredOutput ──────────────────────────────────────────────


def test_structured_output_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        StructuredOutput.model_validate(
            {"name": "Decision", "schema": {"type": "object"}, "strict": True, "x": 1}
        )


def test_structured_output_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        StructuredOutput.model_validate({"name": "", "schema": {}})


# ─── contracts: LlmMessage ────────────────────────────────────────────────────


def test_llm_message_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LlmMessage.model_validate(
            {"role": "user", "content": "hello", "extra": "ignored"}
        )


def test_llm_message_role_validation() -> None:
    LlmMessage(role="system", content="system prompt")
    LlmMessage(role="user", content="hello")
    LlmMessage(role="assistant", content="I am helpful")
    LlmMessage(role="tool", content="result", tool_call_id="call-1", name="get_store")


def test_llm_message_content_none_is_valid() -> None:
    msg = LlmMessage(role="assistant")
    assert msg.content is None


# ─── contracts: LlmRequest ────────────────────────────────────────────────────


def test_llm_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LlmRequest.model_validate(
            {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.5,
                "unknown": True,
            }
        )


def test_llm_request_temperature_bounds() -> None:
    LlmRequest.model_validate(
        {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.0}
    )
    LlmRequest.model_validate(
        {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}], "temperature": 2.0}
    )
    with pytest.raises(ValidationError):
        LlmRequest.model_validate(
            {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": -0.1,
            }
        )


def test_llm_request_max_tokens_positive() -> None:
    req = LlmRequest.model_validate(
        {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    )
    assert req.max_tokens == 1
    with pytest.raises(ValidationError):
        LlmRequest.model_validate(
            {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 0,
            }
        )


# ─── contracts: LlmResponse ───────────────────────────────────────────────────


def test_llm_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LlmResponse.model_validate(
            {
                "id": "resp-1",
                "model": "gpt-4",
                "content": "hello",
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "x": 1,
            }
        )


# ─── contracts: LlmError hierarchy ──────────────────────────────────────────


def test_llm_error_attributes() -> None:
    err = LlmError("validation_error", "bad input")
    assert err.code == "validation_error"
    assert err.message == "bad input"
    assert err.retryable is False
    assert "bad input" in str(err)


def test_llm_error_retryable() -> None:
    err = LlmError("rate_limit", "slow down", retryable=True)
    assert err.retryable is True


def test_authentication_error_not_retryable() -> None:
    err = AuthenticationError("bad key")
    assert err.code == "provider_error"
    assert err.retryable is False
    assert "bad key" in str(err)


def test_rate_limit_error_retryable() -> None:
    err = RateLimitError("slow down")
    assert err.code == "provider_error"
    assert err.retryable is True


def test_invalid_structured_output_error_not_retryable() -> None:
    err = InvalidStructuredOutputError("model refused")
    assert err.code == "provider_error"
    assert err.retryable is False


def test_tool_call_error_not_retryable() -> None:
    err = ToolCallError("malformed tool response")
    assert err.code == "provider_error"
    assert err.retryable is False


def test_tool_call_error_retryable_flag() -> None:
    err = ToolCallError("transient tool error", retryable=True)
    assert err.retryable is True


def test_configuration_error_code() -> None:
    err = ConfigurationError("missing api_key")
    assert err.code == "configuration_error"
    assert err.retryable is False


def test_provider_error_retryable_false() -> None:
    err = ProviderError("connection refused")
    assert err.code == "provider_error"
    assert err.retryable is False


def test_provider_error_retryable_true() -> None:
    err = ProviderError("transient failure", retryable=True)
    assert err.retryable is True


def test_request_timeout_retryable() -> None:
    err = RequestTimeout()
    assert err.code == "timeout"
    assert err.retryable is True


def test_request_cancelled() -> None:
    err = RequestCancelled()
    assert err.code == "cancelled"
    assert err.retryable is False


# ─── contracts: LlmTransportResponse ────────────────────────────────────────


def test_llm_transport_response() -> None:
    from retailtwin_api.llm.contracts import LlmTransportResponse

    resp = LlmTransportResponse(status_code=200)
    assert resp.status_code == 200
    assert resp.payload == {}

    resp2 = LlmTransportResponse(status_code=500, payload={"error": "server error"})
    assert resp2.status_code == 500
    assert resp2.payload == {"error": "server error"}


# ─── contracts: LlmProvider abstract boundary ────────────────────────────────


def test_llm_provider_interface_exists() -> None:
    """Verify LlmProvider is importable and has the expected interface contract."""
    from retailtwin_api.llm.contracts import LlmProvider
    assert hasattr(LlmProvider, "complete")


# ─── Tool conversion helpers ───────────────────────────────────────────────────


def test_convert_tools_openai() -> None:
    from retailtwin_api.llm.contracts import LlmTool

    tools = [
        LlmTool(
            name="get_weather",
            description="Get weather for a location",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        )
    ]
    result = _convert_tools_openai(tools)
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "get_weather"
    assert result[0]["function"]["description"] == "Get weather for a location"
    assert result[0]["function"]["parameters"]["properties"]["city"]["type"] == "string"


def test_safe_parse_tool_call_string_args() -> None:
    tc = {"id": "call_1", "function": {"name": "foo", "arguments": '{"a": 1}'}}
    result = _safe_parse_tool_call(tc)
    assert result.name == "foo"
    assert result.arguments == {"a": 1}


def test_safe_parse_tool_call_dict_args() -> None:
    tc = {"id": "call_2", "function": {"name": "bar", "arguments": {"b": 2}}}
    result = _safe_parse_tool_call(tc)
    assert result.name == "bar"
    assert result.arguments == {"b": 2}


def test_safe_parse_tool_call_missing_name_raises() -> None:
    tc = {"id": "call_3", "function": {"arguments": "{}"}}
    with pytest.raises(ToolCallError, match="missing a function name"):
        _safe_parse_tool_call(tc)


def test_safe_parse_tool_call_bad_json_raises() -> None:
    tc = {"id": "call_4", "function": {"name": "bad", "arguments": "not json"}}
    with pytest.raises(ToolCallError, match="malformed arguments"):
        _safe_parse_tool_call(tc)


# ─── ToolChoicePolicy contract ────────────────────────────────────────────────


def test_tool_choice_policy_default() -> None:
    from retailtwin_api.llm.contracts import ToolChoicePolicy

    policy = ToolChoicePolicy()
    assert policy.mode == "tool_choice"
    assert policy.name is None


def test_tool_choice_policy_required_tool() -> None:
    from retailtwin_api.llm.contracts import ToolChoicePolicy

    policy = ToolChoicePolicy(mode="required_tool", name="get_inventory")
    assert policy.mode == "required_tool"
    assert policy.name == "get_inventory"


def test_tool_choice_policy_none_mode() -> None:
    from retailtwin_api.llm.contracts import ToolChoicePolicy

    policy = ToolChoicePolicy(mode="none")
    assert policy.mode == "none"


def test_tool_choice_policy_validate_for_request_none_with_tools_raises() -> None:
    from retailtwin_api.llm.contracts import ToolChoicePolicy, LlmTool

    policy = ToolChoicePolicy(mode="none")
    tools = [LlmTool(name="get_inventory")]
    with pytest.raises(ValueError, match="'none' is invalid when tools are registered"):
        policy.validate_for_request(tools)


def test_tool_choice_policy_validate_for_request_unknown_name_raises() -> None:
    from retailtwin_api.llm.contracts import ToolChoicePolicy, LlmTool

    policy = ToolChoicePolicy(mode="tool_choice", name="nonexistent")
    tools = [LlmTool(name="get_inventory")]
    with pytest.raises(ValueError, match="not in the registered tools"):
        policy.validate_for_request(tools)


def test_tool_choice_policy_validate_for_request_valid() -> None:
    from retailtwin_api.llm.contracts import ToolChoicePolicy, LlmTool

    policy = ToolChoicePolicy(mode="tool_choice", name="get_inventory")
    tools = [LlmTool(name="get_inventory"), LlmTool(name="get_weather")]
    policy.validate_for_request(tools)  # must not raise


def test_tool_choice_policy_validate_none_no_tools() -> None:
    from retailtwin_api.llm.contracts import ToolChoicePolicy

    policy = ToolChoicePolicy(mode="none")
    policy.validate_for_request([])  # must not raise


# ─── LlmRequest with tool_choice ──────────────────────────────────────────────


def test_llm_request_with_tool_choice_required() -> None:
    from retailtwin_api.llm.contracts import LlmRequest, LlmMessage, ToolChoicePolicy, LlmTool

    req = LlmRequest(
        model="gpt-4",
        messages=[LlmMessage(role="user", content="Hi")],
        tools=[LlmTool(name="get_inventory")],
        tool_choice=ToolChoicePolicy(mode="required_tool"),
    )
    assert req.tool_choice is not None
    assert req.tool_choice.mode == "required_tool"


def test_llm_request_with_tool_choice_named() -> None:
    from retailtwin_api.llm.contracts import LlmRequest, LlmMessage, ToolChoicePolicy, LlmTool

    req = LlmRequest(
        model="gpt-4",
        messages=[LlmMessage(role="user", content="Hi")],
        tools=[LlmTool(name="get_inventory"), LlmTool(name="get_weather")],
        tool_choice=ToolChoicePolicy(mode="tool_choice", name="get_inventory"),
    )
    assert req.tool_choice is not None
    assert req.tool_choice.name == "get_inventory"


# ─── LlmResponse schema validation ───────────────────────────────────────────


def test_validate_structured_output_valid() -> None:
    from retailtwin_api.llm.contracts import LlmResponse, InvalidStructuredOutputError

    resp = LlmResponse(
        id="r1",
        model="gpt-4",
        content='{"decision":"buy","quantity":5}',
    )
    schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "quantity": {"type": "integer"},
        },
        "required": ["decision", "quantity"],
    }
    resp.validate_structured_output(schema)  # must not raise


def test_validate_structured_output_invalid_json_raises() -> None:
    from retailtwin_api.llm.contracts import LlmResponse, InvalidStructuredOutputError

    resp = LlmResponse(
        id="r2",
        model="gpt-4",
        content='not valid json at all',
    )
    schema = {"type": "object"}
    with pytest.raises(InvalidStructuredOutputError, match="not valid JSON"):
        resp.validate_structured_output(schema)


def test_validate_structured_output_conforms_to_schema() -> None:
    from retailtwin_api.llm.contracts import LlmResponse, InvalidStructuredOutputError

    resp = LlmResponse(
        id="r3",
        model="gpt-4",
        content='{"wrong_field":"value"}',  # missing required fields
    )
    schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
        },
        "required": ["decision"],
    }
    with pytest.raises(InvalidStructuredOutputError, match="does not conform"):
        resp.validate_structured_output(schema)


def test_validate_structured_output_none_content_raises() -> None:
    from retailtwin_api.llm.contracts import LlmResponse, InvalidStructuredOutputError

    resp = LlmResponse(
        id="r4",
        model="gpt-4",
        content=None,
    )
    schema = {"type": "object"}
    with pytest.raises(InvalidStructuredOutputError, match="no content"):
        resp.validate_structured_output(schema)


def test_validate_structured_output_wrong_type_raises() -> None:
    from retailtwin_api.llm.contracts import LlmResponse, InvalidStructuredOutputError

    resp = LlmResponse(
        id="r5",
        model="gpt-4",
        content='42',  # integer, not object
    )
    schema = {"type": "object"}
    with pytest.raises(InvalidStructuredOutputError, match="does not conform"):
        resp.validate_structured_output(schema)


# ─── OpenAI adapter: tool_choice policy ──────────────────────────────────────


def test_openai_adapter_sends_tool_choice_required(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-tc1",
            "model": "gpt-4",
            "choices": [{"message": {"content": None, "tool_calls": []}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory")]
    policy = ToolChoicePolicy(mode="required_tool")
    asyncio.run(provider.complete(make_request(tools=tools, tool_choice=policy)))

    sent_payload = client.calls[0][1]["json"]
    assert sent_payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "get_inventory"},
    }


def test_openai_adapter_sends_tool_choice_named(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-tc2",
            "model": "gpt-4",
            "choices": [{"message": {"content": None, "tool_calls": []}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory"), LlmTool(name="get_weather")]
    policy = ToolChoicePolicy(mode="tool_choice", name="get_weather")
    asyncio.run(provider.complete(make_request(tools=tools, tool_choice=policy)))

    sent_payload = client.calls[0][1]["json"]
    assert sent_payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "get_weather"},
    }


def test_openai_adapter_sends_tool_choice_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-tc3",
            "model": "gpt-4",
            "choices": [{"message": {"content": None, "tool_calls": []}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory")]
    policy = ToolChoicePolicy(mode="tool_choice")
    asyncio.run(provider.complete(make_request(tools=tools, tool_choice=policy)))

    sent_payload = client.calls[0][1]["json"]
    assert sent_payload["tool_choice"] == "auto"


def test_openai_adapter_sends_tool_choice_none(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-tc4",
            "model": "gpt-4",
            "choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory")]
    policy = ToolChoicePolicy(mode="none")
    asyncio.run(provider.complete(make_request(tools=tools, tool_choice=policy)))

    sent_payload = client.calls[0][1]["json"]
    assert sent_payload["tool_choice"] == "none"


def test_openai_adapter_no_tool_choice_field_when_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """When tool_choice is None, no tool_choice key should appear in the payload."""
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-tc5",
            "model": "gpt-4",
            "choices": [{"message": {"content": None, "tool_calls": []}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    tools = [LlmTool(name="get_inventory")]
    asyncio.run(provider.complete(make_request(tools=tools)))

    sent_payload = client.calls[0][1]["json"]
    assert "tool_choice" not in sent_payload


# ─── OpenAI adapter: full request/response cycle integration ──────────────────



def test_openai_full_request_response_cycle_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the complete OpenAI-compatible request/response cycle end-to-end.

    Mocks httpx to intercept the actual POST payload and returns a
    fully-formed response so we can verify every field without any real API key.

    Verified contract:
      - model: sent as-is
      - messages: serialised via model_dump()
      - tools: converted to OpenAI function-declaration format
      - tool_choice: emitted as named-function policy
      - response_format: emitted as json_schema with name + schema + strict
      - response: parsed back to LlmResponse with correct content, tool_calls,
        usage, and finish_reason
    """
    # Capture the exact payload so we can assert on every field
    captured_payload: dict[str, object] = {}

    class CycleMockClient:
        """Minimal async context-manager that records the request payload."""

        async def __aenter__(self: "CycleMockClient") -> "CycleMockClient":
            return self

        async def __aexit__(self: "CycleMockClient", *_: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
        ) -> MockResponse:
            captured_payload.update({
                "url": url,
                "headers": headers,
                "json": json,
            })
            return MockResponse({
                "id": "chatcmpl-full-cycle",
                "model": "gpt-4o-mini",
                "choices": [{
                    "message": {
                        "content": '{"action":"order","sku":"P042","quantity":3}',
                        "tool_calls": [
                            {
                                "id": "call_cycle_001",
                                "function": {
                                    "name": "order_item",
                                    "arguments": '{"sku":"P042","qty":3}',
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 42, "completion_tokens": 17, "total_tokens": 59},
            })

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: CycleMockClient())

    provider = OpenAiCompatibleProvider(
        base_url="https://api.openai.com/v1",
        api_key="sk-test-full-cycle",
        model="gpt-4o-mini",
        timeout=60.0,
    )

    # Build a request exercising every field
    tools = [
        LlmTool(
            name="order_item",
            description="Place an order for a product",
            parameters={
                "type": "object",
                "properties": {
                    "sku": {"type": "string", "description": "Product SKU"},
                    "qty": {"type": "integer", "description": "Quantity to order"},
                },
                "required": ["sku", "qty"],
            },
        ),
    ]
    policy = ToolChoicePolicy(mode="tool_choice", name="order_item")
    structured_output = StructuredOutput(
        name="OrderAction",
        schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "sku": {"type": "string"},
                "quantity": {"type": "integer"},
            },
            "required": ["action", "sku", "quantity"],
        },
        strict=True,
    )
    request = LlmRequest(
        model="gpt-4o-mini",
        messages=[
            LlmMessage(role="system", content="You are a retail assistant."),
            LlmMessage(role="user", content="Order 3 units of P042."),
        ],
        temperature=0.7,
        max_tokens=512,
        tools=tools,
        tool_choice=policy,
        structured_output=structured_output,
    )

    response = asyncio.run(provider.complete(request))

    # ── Verify URL & auth headers ────────────────────────────────────────────
    payload = captured_payload["json"]
    assert captured_payload["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured_payload["headers"] == {
        "Authorization": "Bearer sk-test-full-cycle",
        "Content-Type": "application/json",
    }

    # ── model ────────────────────────────────────────────────────────────────
    assert payload["model"] == "gpt-4o-mini"

    # ── messages (serialised via model_dump()) ──────────────────────────────
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][0]["content"] == "You are a retail assistant."
    assert payload["messages"][1]["role"] == "user"
    assert payload["messages"][1]["content"] == "Order 3 units of P042."

    # ── optional top-level fields ────────────────────────────────────────────
    assert payload["temperature"] == 0.7
    assert payload["max_tokens"] == 512

    # ── tools (OpenAI function-declaration format) ──────────────────────────
    assert "tools" in payload
    tools_list = payload["tools"]
    assert len(tools_list) == 1
    assert tools_list[0]["type"] == "function"
    assert tools_list[0]["function"]["name"] == "order_item"
    assert tools_list[0]["function"]["description"] == "Place an order for a product"
    assert tools_list[0]["function"]["parameters"] == {
        "type": "object",
        "properties": {
            "sku": {"type": "string", "description": "Product SKU"},
            "qty": {"type": "integer", "description": "Quantity to order"},
        },
        "required": ["sku", "qty"],
    }

    # ── tool_choice (named function policy) ──────────────────────────────────
    assert "tool_choice" in payload
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "order_item"},
    }

    # ── response_format (structured output) ──────────────────────────────────
    assert "response_format" in payload
    rf = payload["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "OrderAction"
    assert rf["json_schema"]["strict"] is True
    assert "properties" in rf["json_schema"]["schema"]

    # ── response parsing ─────────────────────────────────────────────────────
    assert response.id == "chatcmpl-full-cycle"
    assert response.model == "gpt-4o-mini"
    assert response.content == '{"action":"order","sku":"P042","quantity":3}'
    assert response.finish_reason == "tool_calls"
    assert response.usage.prompt_tokens == 42
    assert response.usage.completion_tokens == 17
    assert response.usage.total_tokens == 59

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_cycle_001"
    assert response.tool_calls[0].name == "order_item"
    assert response.tool_calls[0].arguments == {"sku": "P042", "qty": 3}


# ─── OpenAI adapter: schema validation on response ─────────────────────────────


def test_openai_adapter_validates_schema_on_response_conformant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conformant JSON is accepted without raising."""
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-sv1",
            "model": "gpt-4",
            "choices": [{
                "message": {"content": '{"decision":"buy","quantity":5}'},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    so = StructuredOutput(
        name="Decision",
        schema={
            "type": "object",
            "properties": {
                "decision": {"type": "string"},
                "quantity": {"type": "integer"},
            },
            "required": ["decision", "quantity"],
        },
    )
    response = asyncio.run(provider.complete(make_request(structured_output=so)))
    assert response.content == '{"decision":"buy","quantity":5}'


def test_openai_adapter_validates_schema_on_response_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid JSON raises InvalidStructuredOutputError."""
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-sv2",
            "model": "gpt-4",
            "choices": [{
                "message": {"content": "not json at all {{{"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    so = StructuredOutput(
        name="Decision",
        schema={"type": "object", "properties": {"decision": {"type": "string"}}},
    )
    with pytest.raises(InvalidStructuredOutputError, match="not valid JSON"):
        asyncio.run(provider.complete(make_request(structured_output=so)))


def test_openai_adapter_validates_schema_on_response_non_conformant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid JSON that doesn't match the schema raises InvalidStructuredOutputError."""
    client = MockClient(
        MockResponse({
            "id": "chatcmpl-sv3",
            "model": "gpt-4",
            "choices": [{
                "message": {"content": '{"wrong_field":"value"}'},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = OpenAiCompatibleProvider(
        base_url="https://api.test/v1",
        api_key="key",
        model="gpt-4",
        timeout=30,
    )
    so = StructuredOutput(
        name="Decision",
        schema={
            "type": "object",
            "properties": {"decision": {"type": "string"}},
            "required": ["decision"],
        },
    )
    with pytest.raises(InvalidStructuredOutputError, match="does not conform"):
        asyncio.run(provider.complete(make_request(structured_output=so)))
