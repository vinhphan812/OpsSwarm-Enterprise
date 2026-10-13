# Orchestrator Agent

Coordinates the autonomous control loop and delegates investigation, planning, simulation, execution, and verification.

The orchestrator does not directly mutate the live twin.

## LLM Provider

The orchestrator uses a provider-neutral `LlmProvider` interface from `retailtwin_api.llm`.

### Providers

| Provider | Config | Credentials | Use |
|---|---|---|---|
| `fake` | `LLM_PROVIDER=fake` | None | Tests, local dev, CI |
| `openai_compatible` | `LLM_PROVIDER=openai_compatible` | `LLM_BASE_URL`, `LLM_API_KEY` | Local proxies, OpenAI, Azure |
| `vertex_gemini` | `LLM_PROVIDER=vertex_gemini` | GCP ADC | Production — Gemini on Vertex AI |

### Using FakeLlmProvider in Tests

```python
from retailtwin_api.llm import FakeLlmProvider, LlmRequest, LlmMessage

provider = FakeLlmProvider(
    responses=[
        FakeLlmProvider.Response(content="Order 5 units of P017."),
        FakeLlmProvider.Response(
            tool_calls=[
                LlmToolCall(id="call_1", name="order_item", arguments={"sku": "P017", "qty": 5})
            ],
            finish_reason="tool_calls",
        ),
    ],
)
```

Always inject the fake provider in tests — no real LLM is called in CI.

See `docs/IMPLEMENTATION_GUIDE.md` §12 and `docs/ARCHITECTURE.md` for the full provider architecture.
