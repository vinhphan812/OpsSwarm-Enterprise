# 0021. Require one Gemini inventory read

Date: 2026-10-14

## Status

Accepted

## Context

Issue #2 asks Gemini on Vertex AI to call one real read tool and return the current Live Twin document. A prose answer would be a chatbot. The allow-listed registry already serves `get_inventory` (ADR 0009), and the provider-neutral runtime already has a Vertex adapter (ADR 0008). That adapter sends `functionDeclarations` and does not send `toolConfig`, so Gemini can ignore the tool and answer in text.

The store registry also names simulation and commit tools. Those handlers do not mutate the twin, but this proof must not offer them. Issue #136 (ADR 0020, open PR #178) chooses which provider may be constructed in production. This record does not decide that policy and does not supersede ADR 0008 or ADR 0009.

A missing SKU has to be a controlled tool error. A missing tool call has to fail closed. Credentials and chain-of-thought must not be stored. Gates G02–G06 and foundation gate #10 are separate evidence and stay unpassed.

## Decision

`read_inventory` in `apps/api/retailtwin_api/agents/orchestrator/inventory_read.py` asks the injected `LlmProvider` for exactly one `get_inventory` call (`ToolChoicePolicy` mode `required_tool`, name `get_inventory`). The request lists that tool only. The call is executed with `READ` granted, through the existing registry, against `LiveTwinRepository.get_inventory`. The typed `ProductInventory` document is the result. `updated_at` is not part of it. Model prose is ignored.

No call, more than one call, a different tool, or a different SKU raises `InventoryReadError` and does not execute. A SKU the twin does not have returns `ToolResult` `ok=false` and `error_code=not_found`. A provider failure uses the same error type and does not copy the provider message. Logs carry `correlation_id`, `sku`, the tool name, `ok`, and `error_code` only.

The Vertex adapter maps an absent tool choice to no `toolConfig`. `required_tool`, and a named `tool_choice`, become `functionCallingConfig.mode=ANY` with `allowedFunctionNames`. An unnamed `tool_choice` is `AUTO`. `none` is `NONE`. This read also sets metadata `vertex_thinking_budget=0`, which the adapter copies to `generationConfig.thinkingConfig`. Other requests that omit the key are unchanged. CI uses `FakeLlmProvider` and does not call Vertex. A live call is opt-in (`RETAILTWIN_VERTEX_LIVE=1`), uses Application Default Credentials, project `retailtwin-ai-511002`, location `us-central1`, and model `gemini-2.5-flash`, and only reads.

## Consequences

One SKU can be proven against the twin the model was not allowed to paraphrase. Write tools are not on this request. The module does not import a model SDK and does not write Firestore, BigQuery, or the Live Twin. The day-0 Cloud Run service still does not construct a provider. Issue #136 remains a separate pull request. No API key is read or committed. Passing this read does not pass gate #10 or G02–G06.

- Pull request:
- Issue: #2
- Supersedes:
- Superseded by:
