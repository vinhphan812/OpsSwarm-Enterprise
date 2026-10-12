# ADR-0008: Provider-Neutral LLM Runtime

## Context
RetailTwin AI currently calls Gemini directly via Vertex AI SDK. For development and local testing, and to ensure flexibility, we need an abstraction layer that allows switching providers (e.g., to OpenAI or local models) without changing core agent logic.

## Decision
Introduce a provider-neutral interface `LLMProvider` in a new `services/ai` namespace.

1. **Interface**: Define `LLMProvider` abstract base class with `generate_content(prompt: str, ...) -> str`.
2. **Implementation**:
    - `VertexAIProvider`: For production Vertex Gemini invocation.
    - `OpenAICompatibleProvider`: For dev/local OpenAI or compatible endpoints (e.g., local LLM servers).
3. **Configuration**: Use `Settings` (Pydantic) to switch provider based on `LLM_PROVIDER` env var:
    - **Development / local**: `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
    - **Production (Vertex AI)**: `LLM_PROVIDER=vertex_gemini`, `LLM_MODEL`, `GOOGLE_CLOUD_PROJECT=retailtwin-ai-511002`, `GOOGLE_CLOUD_LOCATION=us-central1`
4. **Production auth**: Vertex AI authentication uses Application Default Credentials (ADC) via the Cloud Run service identity. Service-account key files are never used in production.
5. **Agent Refactoring**: Agents call `LLMProvider`, not the concrete SDKs directly.

## Consequences
- Agents are decoupled from specific SDKs.
- Local development is drastically improved with OpenAI-compatible mocks/local LLMs, reducing costs and latency for dev.
- Production remains solid with Vertex AI.
- Adds slight boilerplate for the factory and provider classes.

## Implementation Tasks (Planned)
- [ ] Task 1: Create `services/ai/interface.py` defining `LLMProvider`.
- [ ] Task 2: Create `services/ai/factory.py` for provider initialization.
- [ ] Task 3: Implement `VertexAIProvider` and `OpenAICompatibleProvider` in `services/ai/providers/`.
- [ ] Task 4: Refactor Agents to inject `LLMProvider`.
