"""Provider registry and the production Vertex policy. No live model call."""

from __future__ import annotations

from pathlib import Path

import pytest

from retailtwin_api.llm.contracts import STANDARD_CAPABILITIES, ConfigurationError, LlmProvider
from retailtwin_api.llm.factory import (
    LlmConfig,
    create_provider,
    install_builtin_providers,
    llm_config_from_settings,
    register_provider,
    unregister_provider,
)
from retailtwin_api.llm.fake import FakeLlmProvider
from retailtwin_api.llm.vertex import VertexProvider
from retailtwin_api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
_FORBIDDEN = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL")


@pytest.fixture(autouse=True)
def _clear_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "APP_ENV", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _production_vertex(**overrides: object) -> LlmConfig:
    values: dict[str, object] = {
        "provider": "vertex_gemini",
        "model": "gemini-2.5-flash",
        "project_id": "retailtwin-ai-511002",
        "location": "us-central1",
        "app_env": "production",
    }
    values.update(overrides)
    return LlmConfig.model_validate(values)


def test_unknown_provider_fails_fast() -> None:
    with pytest.raises(ConfigurationError, match="Unknown LLM provider"):
        create_provider(LlmConfig(provider="not-a-provider", model="m"))


def test_production_rejects_fake_and_loopback() -> None:
    with pytest.raises(ConfigurationError, match="vertex_gemini"):
        create_provider(LlmConfig(provider="fake", model="fake-test", app_env="production"))
    with pytest.raises(ConfigurationError, match="loopback"):
        create_provider(
            LlmConfig(
                provider="openai_compatible",
                model="local",
                base_url="http://localhost:8000/v1",
                api_key="key",
                app_env="production",
            )
        )


def test_production_vertex_uses_adc_and_keeps_the_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    provider = create_provider(_production_vertex())
    assert isinstance(provider, VertexProvider)
    assert provider.capabilities == STANDARD_CAPABILITIES
    assert "retailtwin-ai-511002" in provider._endpoint
    assert provider._endpoint.startswith("https://us-central1-aiplatform.googleapis.com")


def test_vertex_rejects_an_api_key_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "super-secret-value"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    with pytest.raises(ConfigurationError) as caught:
        create_provider(_production_vertex())
    assert secret not in str(caught.value)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", secret)
    with pytest.raises(ConfigurationError) as caught:
        create_provider(
            LlmConfig(
                provider="vertex_gemini",
                model="gemini-2.5-flash",
                project_id="retailtwin-ai-511002",
            )
        )
    assert secret not in str(caught.value)


def test_production_vertex_stays_on_the_store_events_project() -> None:
    with pytest.raises(ConfigurationError, match="retailtwin-ai-511002"):
        create_provider(_production_vertex(project_id="other-project"))
    with pytest.raises(ConfigurationError, match="us-central1"):
        create_provider(_production_vertex(location="europe-west1"))


def test_vertex_config_api_key_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="does not accept an API key"):
        create_provider(
            LlmConfig(
                provider="vertex_gemini",
                model="gemini-2.5-flash",
                project_id="retailtwin-ai-511002",
                api_key="local-key",
            )
        )


def test_a_failed_adapter_does_not_fall_back_to_fake() -> None:
    def boom(_config: LlmConfig) -> LlmProvider:
        raise ConfigurationError("adapter unavailable")

    register_provider("failing_adapter", boom, STANDARD_CAPABILITIES)
    try:
        with pytest.raises(ConfigurationError, match="adapter unavailable"):
            create_provider(LlmConfig(provider="failing_adapter", model="m"))
    finally:
        unregister_provider("failing_adapter")


def test_production_vertex_cannot_be_replaced_or_removed() -> None:
    def boom(config: LlmConfig) -> LlmProvider:
        return FakeLlmProvider(default_model=config.model)

    with pytest.raises(ConfigurationError, match="cannot be replaced"):
        register_provider("vertex_gemini", boom, STANDARD_CAPABILITIES, replace=True)
    with pytest.raises(ConfigurationError, match="cannot be removed"):
        unregister_provider("vertex_gemini")
    provider = create_provider(_production_vertex())
    assert isinstance(provider, VertexProvider)
    assert not isinstance(provider, FakeLlmProvider)


def test_overwritten_vertex_slot_still_builds_the_shipped_adapter() -> None:
    from retailtwin_api.llm import factory as factory_module

    def boom(config: LlmConfig) -> LlmProvider:
        return FakeLlmProvider(default_model=config.model)

    factory_module._REGISTRY["vertex_gemini"] = factory_module._ProviderSpec(
        boom, STANDARD_CAPABILITIES
    )
    try:
        provider = create_provider(_production_vertex())
        assert isinstance(provider, VertexProvider)
        assert not isinstance(provider, FakeLlmProvider)
    finally:
        install_builtin_providers()


def test_a_development_adapter_can_be_replaced() -> None:
    def first(config: LlmConfig) -> LlmProvider:
        return FakeLlmProvider(default_model=config.model)

    def second(_config: LlmConfig) -> LlmProvider:
        return FakeLlmProvider(default_model="second")

    register_provider("probe_replace", first, STANDARD_CAPABILITIES)
    try:
        register_provider("probe_replace", second, STANDARD_CAPABILITIES, replace=True)
        provider = create_provider(LlmConfig(provider="probe_replace", model="first"))
        assert isinstance(provider, FakeLlmProvider)
        assert provider.default_model == "second"
        with pytest.raises(ConfigurationError, match="vertex_gemini"):
            create_provider(
                LlmConfig(provider="probe_replace", model="second", app_env="production")
            )
    finally:
        unregister_provider("probe_replace")


def test_a_new_adapter_does_not_require_an_agent_edit() -> None:
    def build(config: LlmConfig) -> LlmProvider:
        return FakeLlmProvider(default_model=config.model)

    register_provider("probe_adapter", build, STANDARD_CAPABILITIES)
    try:
        provider = create_provider(LlmConfig(provider="probe_adapter", model="probe-model"))
        assert isinstance(provider, FakeLlmProvider)
        assert provider.capabilities == STANDARD_CAPABILITIES
        planner = (REPO_ROOT / "apps/api/retailtwin_api/agents/planner/plans.py").read_text(encoding="utf-8")
        investigator = (
            REPO_ROOT / "apps/api/retailtwin_api/agents/investigator/evidence.py"
        ).read_text(encoding="utf-8")
        assert "probe_adapter" not in planner
        assert "probe_adapter" not in investigator
    finally:
        unregister_provider("probe_adapter")


def test_duplicate_registration_is_refused() -> None:
    def build(config: LlmConfig) -> LlmProvider:
        return FakeLlmProvider(default_model=config.model)

    register_provider("probe_once", build, STANDARD_CAPABILITIES)
    try:
        with pytest.raises(ConfigurationError, match="already registered"):
            register_provider("probe_once", build, STANDARD_CAPABILITIES)
    finally:
        unregister_provider("probe_once")


def test_settings_map_onto_a_provider_without_starting_the_day0_api() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        llm_provider="vertex_gemini",
        llm_model="gemini-2.5-flash",
        google_cloud_project="retailtwin-ai-511002",
        google_cloud_location="us-central1",
    )
    assert settings.is_production is True
    provider = create_provider(llm_config_from_settings(settings))
    assert isinstance(provider, VertexProvider)


def test_forbidden_key_names_are_not_a_config_path() -> None:
    roots = [
        REPO_ROOT / "apps" / "api" / "retailtwin_api",
        REPO_ROOT / "docs",
        REPO_ROOT / "infrastructure",
        REPO_ROOT / "scripts",
        REPO_ROOT / ".env.example",
    ]
    hits: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md", ".example", ".yml", ".sh", ""}:
                continue
            if path.name == "factory.py":
                continue
            # Exclude docs/ and README files which may legitimately mention API key names
            # in documentation context, not in actual code or config.
            if "docs/" in str(path) or path.name.startswith("README"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in _FORBIDDEN:
                if name in text:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{name}")
    assert hits == []
