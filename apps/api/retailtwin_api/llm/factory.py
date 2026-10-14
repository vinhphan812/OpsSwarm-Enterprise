"""Configuration and registry for LLM providers.

Agent code asks `create_provider` for an `LlmProvider`. Adding an adapter
registers a builder here. It does not add a branch to the planner, the
investigator, or the tool registry.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from retailtwin_api.settings import Settings

from .contracts import (
    STANDARD_CAPABILITIES,
    ConfigurationError,
    LlmProvider,
    ProviderCapabilities,
)
from .fake import FakeLlmProvider
from .openai_compatible import OpenAiCompatibleProvider
from .vertex import VertexProvider

_PRODUCTION_PROJECT = "retailtwin-ai-511002"
_PRODUCTION_LOCATION = "us-central1"
# Rejected as credentials. The values are never read into a request and never logged.
_FORBIDDEN_KEY_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class LlmConfig(BaseModel):
    """Configuration used to instantiate a provider adapter.

    ``base_url`` for ``openai_compatible`` is read from ``LLM_BASE_URL`` when
    omitted. There is no default host, so a missing value cannot reach the
    public OpenAI API. ``app_env`` left empty reads ``APP_ENV``.
    """

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key: str | None = None
    project_id: str | None = None
    location: str = "us-central1"
    timeout: float = Field(default=30.0, gt=0)
    app_env: str | None = None

    @field_validator("provider")
    @classmethod
    def _provider_name(cls, value: str) -> str:
        text = value.strip()
        if not text or "\n" in value or "\r" in value:
            raise ValueError("provider name is blank.")
        return text


@dataclass(frozen=True)
class _ProviderSpec:
    build: Callable[[LlmConfig], LlmProvider]
    capabilities: ProviderCapabilities


_REGISTRY: dict[str, _ProviderSpec] = {}


def register_provider(
    name: str,
    build: Callable[[LlmConfig], LlmProvider],
    capabilities: ProviderCapabilities,
    *,
    replace: bool = False,
) -> None:
    """Register one adapter. A second registration of the same name is refused."""

    if not name.strip() or "\n" in name or "\r" in name:
        raise ConfigurationError("provider name is blank.")
    if name in _REGISTRY and not replace:
        raise ConfigurationError(f"LLM provider {name!r} is already registered.")
    _REGISTRY[name] = _ProviderSpec(build, capabilities)


def unregister_provider(name: str) -> None:
    """Drop a test adapter. Built-ins are restored with ``install_builtin_providers``."""

    _REGISTRY.pop(name, None)


def install_builtin_providers() -> None:
    """Register the three adapters shipped with the API."""

    register_provider("fake", _build_fake, STANDARD_CAPABILITIES, replace=True)
    register_provider("openai_compatible", _build_openai, STANDARD_CAPABILITIES, replace=True)
    register_provider("vertex_gemini", _build_vertex, STANDARD_CAPABILITIES, replace=True)


def llm_config_from_settings(settings: Settings) -> LlmConfig:
    """Copy the process settings into a provider config. The API key is not logged."""

    return LlmConfig(
        provider=settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        project_id=settings.google_cloud_project,
        location=settings.google_cloud_location,
        timeout=settings.llm_timeout_seconds,
        app_env=settings.app_env,
    )


def create_provider(config: LlmConfig) -> LlmProvider:
    """Create the configured adapter. A failed build is not replaced with the fake provider."""

    _enforce(config)
    spec = _REGISTRY.get(config.provider)
    if spec is None:
        raise ConfigurationError(f"Unknown LLM provider {config.provider!r}.")
    provider = spec.build(config)
    provider.capabilities = spec.capabilities
    return provider


def _app_env(config: LlmConfig) -> str:
    if config.app_env is not None:
        return config.app_env.strip().lower()
    return os.environ.get("APP_ENV", "development").strip().lower()


def _loopback(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def _reject_forbidden_keys() -> None:
    for name in _FORBIDDEN_KEY_ENV:
        if os.environ.get(name):
            raise ConfigurationError(
                "Vertex and production inference do not accept an API key. "
                "Use Application Default Credentials."
            )


def _enforce(config: LlmConfig) -> None:
    app_env = _app_env(config)
    if config.base_url and _loopback(config.base_url) and (
        app_env == "production" or config.provider == "vertex_gemini"
    ):
        raise ConfigurationError("production inference does not accept a loopback endpoint.")
    if app_env == "production" and config.provider != "vertex_gemini":
        raise ConfigurationError("production LLM_PROVIDER must be vertex_gemini")
    if config.provider != "vertex_gemini":
        return
    _reject_forbidden_keys()
    if config.api_key:
        raise ConfigurationError("vertex_gemini does not accept an API key.")
    if app_env != "production":
        return
    if config.project_id != _PRODUCTION_PROJECT:
        raise ConfigurationError("production Vertex stays on retailtwin-ai-511002.")
    if config.location != _PRODUCTION_LOCATION:
        raise ConfigurationError("production Vertex stays in us-central1.")


def _build_fake(config: LlmConfig) -> LlmProvider:
    return FakeLlmProvider(default_model=config.model)


def _build_openai(config: LlmConfig) -> LlmProvider:
    base_url = config.base_url or os.environ.get("LLM_BASE_URL")
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


def _build_vertex(config: LlmConfig) -> LlmProvider:
    project_id = config.project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        raise ConfigurationError("project_id is required for the vertex_gemini provider")
    return VertexProvider(
        project_id=project_id,
        location=config.location,
        model=config.model,
        timeout=config.timeout,
    )


install_builtin_providers()
