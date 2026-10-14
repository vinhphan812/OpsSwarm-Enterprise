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

None of those handlers change the store or issue a commit authorization. `forecast_demand`, `get_stockout_risk`, `get_promotions`, and the other analytical catalog names stay off this list until a deterministic port is bound with `bind_catalog_tool`. A call also needs the matching capability in `granted`. Unknown names, invalid arguments, missing permission, and timeouts return a controlled `ToolResult`.

The live Vertex proof that Gemini calls `get_inventory` stays with issue #2. Tests use `FakeLlmProvider` and the same `LlmTool` list.

## Stale recovery

ADR 0018. Import `replan` from `retailtwin_api.agents.orchestrator.replan`. It is the recovery loop for a `REFRESH_REQUIRED` verdict.

| Input | Role |
| --- | --- |
| `Decision` | The decision the guard is about to accept or reject. It is not modified. |
| `InvestigationStart` | The original sale. The correlation id and store id stay on every refresh. |
| `LlmProvider` | One injected provider. Investigator and planner both receive it. |
| `ToolRegistry` | Read tools for the refresh. The caller binds them to current evidence. |
| `NoStaleCommit` | Authorizes, then rechecks, on fresh Live Twin reads. |
| `ContextVersionSource` | Read after each evidence refresh, for the same store. `plan` receives that version. The rejected decision is not copied. |
| `CommitPort` | Called only after `ALLOW` survives `recheck`, with that binding. |
| `SimulationPort` | Optional. Scores the new decisions. Absent means `kpi_score` stays `-1.0`. |

`RETAILTWIN_REPLAN_MAX_REFRESHES` defaults to 1. `0` is valid and stops on the first stale verdict, before the context source is read. The count is the number of evidence refreshes, not model retries and not live commit attempts. Each refresh that does run reads the context source once, after `investigate` returns and before `plan`. A second stale verdict reads it again. A blank or failed read stops the run. A new decision that does not carry the version just read stops the run, including when the simulation port rewrites it.

`COMMITTED` is the only status that called the commit port. `DENIED` and `HUMAN_REVIEW` stop. `RETRY_LIMIT` means the next refresh would pass the bound; nothing is committed. `FAILED` means the provider, planner, simulation port, or commit port stopped the run. Logs carry `correlation_id`, `decision_id`, the status, and the reason code. They do not carry model prose or credentials.

The commit port is not a Live Twin writer by itself. A production adapter still has to redeem a guarded Executor authorization. This module does not import that executor, the simulator, or a model SDK. No route calls `replan`.
