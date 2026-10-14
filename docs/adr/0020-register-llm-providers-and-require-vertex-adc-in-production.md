# 0020. Register LLM providers and require Vertex ADC in production

Date: 2026-10-14

## Status

Accepted

## Context

ADR 0008 keeps agent code on one provider-neutral `LlmProvider`. The factory that followed it is a closed `if/else` on three names, and `.env.example` still advertised a Gemini model variable. Issue #136 asks for a configuration-driven choice that production cannot point at a fake provider, a loopback endpoint, or an API key. The live Gemini tool call is still issue #2, and the day-0 Cloud Run service does not construct a provider.

## Decision

`create_provider` looks up a registered builder. The shipped adapters are `fake`, `openai_compatible`, and `vertex_gemini`. Another adapter is a `register_provider` call. It is not an edit to the planner, the investigator, or the tool registry. An unknown name fails. A builder that raises is not replaced with the fake provider.

Each adapter declares the same capability flags: structured output, tool calling, tool-result continuation, native JSON schema, and usage metadata. Callers read the flags.

`LLM_PROVIDER`, `LLM_MODEL`, and `LLM_TIMEOUT_SECONDS` are the common settings. `LLM_BASE_URL` and `LLM_API_KEY` belong only to `openai_compatible`. Vertex takes `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` and authenticates with Application Default Credentials.

When `APP_ENV=production`, `create_provider` accepts only `vertex_gemini` on project `retailtwin-ai-511002` in `us-central1`. A loopback base URL is refused. A Gemini or Google API key in the environment, or an API key on the Vertex config, is refused and is not copied into the error. The day-0 process still starts without constructing a provider, so this check does not change the current Cloud Run revision. Issue #143 still owns the deploy contract, and issue #134 still owns the full cloud matrix.

## Consequences

Local tests keep the fake provider. A compatible endpoint remains available in development. Production inference cannot silently run the fake adapter. Issue #2 is still the proof that Gemini on Vertex calls `get_inventory`. Gates G02–G06 and foundation gate #10 stay unpassed. Issue #6 still owns the Firestore Live Twin.

- Pull request: https://github.com/vinhphan812/retailtwin-ai/pull/178
- Issue: #136
- Supersedes:
- Superseded by:
