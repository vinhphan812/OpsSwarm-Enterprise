"""Tests for FakeLlmProvider."""

import asyncio

import pytest

from retailtwin_api.llm import (
    FakeLlmProvider,
    LlmMessage,
    LlmRequest,
    LlmTool,
    LlmToolCall,
    TokenUsage,
)


# ─── Helpers ───────────────────────────────────────────────────────────────────


def make_request(
    model: str = "fake-model",
    messages: list[LlmMessage] | None = None,
    tools: list[LlmTool] | None = None,
) -> LlmRequest:
    return LlmRequest(
        model=model,
        messages=messages or [LlmMessage(role="user", content="Hello")],
        tools=tools or [],
    )


# ─── Basic responses ────────────────────────────────────────────────────────────


def test_fake_provider_returns_content() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(content="Order 5 units of P017."),
        ],
    )
    response = asyncio.run(provider.complete(make_request()))

    assert response.content == "Order 5 units of P017."
    assert response.finish_reason == "stop"


def test_fake_provider_returns_tool_calls() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                tool_calls=[
                    LlmToolCall(id="call_1", name="order_item", arguments={"sku": "P017", "qty": 5}),
                ],
                finish_reason="tool_calls",
            ),
        ],
    )
    response = asyncio.run(provider.complete(make_request()))

    assert response.content is None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "order_item"
    assert response.tool_calls[0].arguments == {"sku": "P017", "qty": 5}


def test_fake_provider_returns_both_content_and_tool_calls() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                content="I will order the items.",
                tool_calls=[
                    LlmToolCall(id="call_2", name="order_item", arguments={"sku": "P017", "qty": 5}),
                ],
            ),
        ],
    )
    response = asyncio.run(provider.complete(make_request()))

    assert response.content == "I will order the items."
    assert len(response.tool_calls) == 1


def test_fake_provider_respects_response_id_and_model() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                id="resp-custom-42",
                model="custom-model",
                content="Hello, world!",
            ),
        ],
    )
    response = asyncio.run(provider.complete(make_request(model="custom-model")))

    assert response.id == "resp-custom-42"
    assert response.model == "custom-model"


def test_fake_provider_respects_custom_usage() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                content="Hello",
                usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            ),
        ],
    )
    response = asyncio.run(provider.complete(make_request()))

    assert response.usage.prompt_tokens == 100
    assert response.usage.completion_tokens == 50
    assert response.usage.total_tokens == 150


# ─── Default content ────────────────────────────────────────────────────────────


def test_fake_provider_uses_default_content_when_no_response() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(),  # no content, no tool_calls
        ],
    )
    response = asyncio.run(provider.complete(make_request()))

    assert response.content is None
    assert response.finish_reason == "stop"


def test_fake_provider_default_model_when_not_specified() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(content="Hi"),
        ],
    )
    response = asyncio.run(provider.complete(make_request(model="requested-model")))

    assert response.model == "requested-model"


# ─── Call history ──────────────────────────────────────────────────────────────


def test_fake_provider_records_call_history() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(content="First response."),
            FakeLlmProvider.Response(content="Second response."),
        ],
    )

    req1 = make_request(model="model-a")
    req2 = make_request(model="model-b")

    asyncio.run(provider.complete(req1))
    asyncio.run(provider.complete(req2))

    assert provider.call_count == 2
    assert len(provider.call_history) == 2
    assert provider.call_history[0].model == "model-a"
    assert provider.call_history[1].model == "model-b"


def test_fake_provider_call_history_deepcopied() -> None:
    provider = FakeLlmProvider(
        responses=[FakeLlmProvider.Response(content="Hello")],
    )
    req = make_request()
    asyncio.run(provider.complete(req))

    # Mutating the original request does not affect the recorded history
    req.messages[0].content = "Modified"
    assert provider.call_history[0].messages[0].content == "Hello"


# ─── Response queue / exhaustion ────────────────────────────────────────────────


def test_fake_provider_exhaustion_raises() -> None:
    provider = FakeLlmProvider(
        responses=[FakeLlmProvider.Response(content="Only one.")],
    )
    asyncio.run(provider.complete(make_request()))

    with pytest.raises(ValueError, match="no responses left"):
        asyncio.run(provider.complete(make_request()))


def test_fake_provider_push_response() -> None:
    provider = FakeLlmProvider(
        responses=[FakeLlmProvider.Response(content="First.")],
    )
    provider.push_response(FakeLlmProvider.Response(content="Pushed."))

    r1 = asyncio.run(provider.complete(make_request()))
    r2 = asyncio.run(provider.complete(make_request()))

    assert r1.content == "First."
    assert r2.content == "Pushed."


def test_fake_provider_set_responses_replaces_queue() -> None:
    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(content="Old."),
        ],
    )
    provider.set_responses([
        FakeLlmProvider.Response(content="New first."),
        FakeLlmProvider.Response(content="New second."),
    ])

    r1 = asyncio.run(provider.complete(make_request()))
    r2 = asyncio.run(provider.complete(make_request()))

    assert r1.content == "New first."
    assert r2.content == "New second."


def test_fake_provider_no_responses_raises_on_first_call() -> None:
    provider = FakeLlmProvider(responses=[])
    with pytest.raises(ValueError, match="no responses left"):
        asyncio.run(provider.complete(make_request()))


# ─── Factory integration ───────────────────────────────────────────────────────


def test_create_provider_fake() -> None:
    from retailtwin_api.llm.factory import LlmConfig, create_provider

    provider = create_provider(LlmConfig(provider="fake", model="fake-model"))
    assert isinstance(provider, FakeLlmProvider)


def test_create_provider_fake_default_model() -> None:
    from retailtwin_api.llm.factory import LlmConfig, create_provider

    provider = create_provider(LlmConfig(provider="fake", model="my-test-model"))
    # Inject a response so the queue is not empty
    provider.push_response(FakeLlmProvider.Response(content="ok"))
    response = asyncio.run(provider.complete(make_request(model="my-test-model")))
    assert response.model == "my-test-model"
    assert response.content == "ok"


def test_create_provider_fake_with_responses() -> None:
    from retailtwin_api.llm.factory import LlmConfig, create_provider

    provider = create_provider(LlmConfig(provider="fake", model="test"))
    assert isinstance(provider, FakeLlmProvider)
    # Inject responses after creation
    provider.push_response(FakeLlmProvider.Response(content="Injected!"))
    response = asyncio.run(provider.complete(make_request()))
    assert response.content == "Injected!"
