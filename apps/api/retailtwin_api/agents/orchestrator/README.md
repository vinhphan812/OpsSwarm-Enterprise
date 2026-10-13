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

## Tool registry

ADR 0009. The registry in `tool_registry.py` is the only tool list the orchestrator gives the model. One pydantic model produces one `LlmTool`. The existing OpenAI-compatible and Vertex adapters translate that list. There is no second tool definition and no live-write tool.

`build_store_registry(store)` offers these tools:

| Tool | Capability | Effect |
| --- | --- | --- |
| `get_store_state` | READ | Returns the store view |
| `get_shelf_state` | READ | Returns products on one shelf |
| `get_inventory` | READ | Returns one SKU |
| `get_backroom_inventory` | READ | Returns the backroom quantity for one SKU |
| `move_product` | SIMULATION | Records a validated move |
| `change_facings` | SIMULATION | Records a validated facing change |
| `replenish_shelf` | SIMULATION | Records a validated replenishment |
| `create_simulation` | SIMULATION | Allocates a simulation id |
| `submit_action_for_commit` | COMMIT_REQUEST | Records a commit request |

None of those handlers change the store or issue a commit authorization. `forecast_demand`, `get_stockout_risk`, and the other analytical catalog names stay off this list until a deterministic port is bound with `bind_catalog_tool`. A call also needs the matching capability in `granted`. Unknown names, invalid arguments, missing permission, and timeouts return a controlled `ToolResult`.

The live Vertex proof that Gemini calls `get_inventory` stays with issue #2. Tests use `FakeLlmProvider` and the same `LlmTool` list.
