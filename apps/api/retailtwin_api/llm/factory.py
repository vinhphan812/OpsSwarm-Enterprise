"""Configuration and factory for LLM providers."""

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import ConfigurationError, LlmProvider
from .fake import FakeLlmProvider
from .openai_compatible import OpenAiCompatibleProvider
from .vertex import VertexProvider


class LlmConfig(BaseModel):
    """Configuration used to instantiate a provider adapter.

    base_url for the ``openai_compatible`` provider is read from the ``LLM_BASE_URL``
    environment variable when not explicitly provided.  No default is applied
    to avoid accidental routing to the public OpenAI API in production.

    The ``fake`` provider is for tests and local development only.
    """

    provider: Literal["fake", "openai_compatible", "vertex_gemini"]
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key: str | None = None
    project_id: str | None = None
    location: str = "us-central1"
    timeout: float = Field(default=30.0, gt=0)


def create_provider(config: LlmConfig) -> LlmProvider:
    """Create the configured inference adapter without performing inference."""
    if config.provider == "fake":
        return FakeLlmProvider(default_model=config.model)

    if config.provider == "openai_compatible":
        base_url = config.base_url
        if not base_url:
            import os
            base_url = os.environ.get("LLM_BASE_URL")
            if not base_url:
                raise ConfigurationError(
                    "LLM_BASE_URL environment variable or base_url config field is required "
                    "for the 'openai_compatible' provider.  No default is provided."
                )

        return OpenAiCompatibleProvider(
            base_url=base_url,
            api_key=config.api_key or "",
            model=config.model,
            timeout=config.timeout,
        )

    if not config.project_id:
        raise ConfigurationError("project_id is required for the vertex_gemini provider")

    return VertexProvider(
        project_id=config.project_id,
        location=config.location,
        model=config.model,
        timeout=config.timeout,
    )
