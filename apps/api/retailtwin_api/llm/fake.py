"""Deterministic fake LLM provider for testing and local development.

Pass ``responses`` to ``FakeLlmProvider`` to control every call.  A response
is returned unconditionally — no model is consulted, no HTTP request is made.
This makes the provider fully deterministic and free of side-effects, ideal for:

- Unit / integration tests that must not call a real model
- Local development without an API key
- Reproducing a specific conversation path deterministically

Usage::

    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                content="Order 5 units of P017.",
            ),
        ],
    )
    response = await provider.complete(request)

Tool calls are also supported::

    provider = FakeLlmProvider(
        responses=[
            FakeLlmProvider.Response(
                tool_calls=[LlmToolCall(id="call_1", name="order_item", arguments={"sku": "P017", "qty": 5})],
            ),
        ],
    )
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from .contracts import (
    LlmMessage,
    LlmProvider,
    LlmRequest,
    LlmResponse,
    LlmToolCall,
    TokenUsage,
)

__all__ = ["FakeLlmProvider"]


class FakeLlmProvider(LlmProvider):
    """Fake provider that returns pre-configured responses deterministically.

    Every call consumes the next response in ``responses`` in order.  When the
    list is exhausted a ``ValueError`` is raised, so tests fail fast on
    unexpected extra calls rather than silently returning stale data.
    """

    class Response:
        """One pre-configured fake response.

        Either ``content`` *or* ``tool_calls`` (or both) may be set.
        If neither is set the response is empty.
        """

        def __init__(
            self,
            content: str | None = None,
            tool_calls: list[LlmToolCall] | None = None,
            finish_reason: str | None = "stop",
            id: str | None = None,
            model: str | None = None,
            usage: TokenUsage | None = None,
        ) -> None:
            self.content = content
            self.tool_calls = tool_calls or []
            self.finish_reason = finish_reason
            self.id = id or f"fake-{uuid.uuid4().hex[:8]}"
            self.model = model
            self.usage = usage or TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)

    def __init__(
        self,
        responses: list[Response] | None = None,
        *,
        default_content: str = "This is a deterministic fake response.",
        default_model: str = "fake-model",
    ) -> None:
        self._responses: list[FakeLlmProvider.Response] = responses or []
        self._call_count: int = 0
        self._call_history: list[LlmRequest] = []
        self.default_content = default_content
        self.default_model = default_model

    @property
    def call_count(self) -> int:
        """Number of ``complete`` calls made so far."""
        return self._call_count

    @property
    def call_history(self) -> list[LlmRequest]:
        """All ``LlmRequest`` objects ever passed to ``complete``."""
        return self._call_history

    def push_response(self, response: Response) -> None:
        """Append a response to be returned by the next ``complete`` call.

        This lets tests build up a queue of responses as the test progresses,
        even after the provider has been instantiated.
        """
        self._responses.append(response)

    def set_responses(self, responses: list[Response]) -> None:
        """Replace the remaining response queue atomically."""
        self._responses = list(responses)

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Return the next pre-configured response, or raise on exhaustion."""
        self._call_count += 1
        # Record a deep copy so tests can inspect without the caller mutating it
        self._call_history.append(copy.deepcopy(request))

        if not self._responses:
            raise ValueError(
                "FakeLlmProvider: no responses left. "
                f"Call #{self._call_count} was made with request model={request.model!r}. "
                "Push more responses with push_response() or set_responses()."
            )

        resp = self._responses.pop(0)
        return LlmResponse(
            id=resp.id,
            model=resp.model or request.model or self.default_model,
            content=resp.content,
            finish_reason=resp.finish_reason,
            tool_calls=resp.tool_calls,
            usage=resp.usage,
            raw={},
        )
