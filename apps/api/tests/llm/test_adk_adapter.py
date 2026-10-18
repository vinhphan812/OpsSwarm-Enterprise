"""Unit tests for the ADK adapter boundary stub (#21).

These tests pin the contract described in ADR 0042:

- ``AdkLlmProvider`` is dormant by default (``is_configured()`` returns
  ``False``).
- Public methods raise ``NotImplementedError`` so a misconfigured production
  rollout fails closed instead of silently swapping the canonical provider.
- ``register_adk_provider()`` is a no-op while ``ADK_ENABLED`` is unset.
"""

from __future__ import annotations

import pytest

from retailtwin_api.llm.adk_adapter import AdkLlmProvider, is_adk_enabled
from retailtwin_api.llm.adk_register import (
    ADK_PROVIDER_NAME,
    register_adk_provider,
)
from retailtwin_api.llm.contracts import (
    LlmMessage,
    LlmProvider,
    LlmRequest,
    ProviderCapabilities,
)
from retailtwin_api.llm.factory import (
    install_builtin_providers,
    unregister_provider,
)


@pytest.fixture(autouse=True)
def _clear_adk_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``ADK_ENABLED`` is unset unless a specific test opts in."""
    monkeypatch.delenv("ADK_ENABLED", raising=False)
    yield
    # Restore baseline registry between tests so cross-test pollution cannot
    # smuggle the ADK slot in.
    install_builtin_providers()
    unregister_provider(ADK_PROVIDER_NAME)


def test_adk_provider_is_a_subclass_of_llm_provider() -> None:
    """The stub must implement the provider-neutral ``LlmProvider`` interface."""

    assert issubclass(AdkLlmProvider, LlmProvider)


def test_adk_provider_is_dormant_by_default() -> None:
    """``is_configured()`` must return ``False`` — the stub never activates."""

    provider = AdkLlmProvider()
    assert provider.is_configured() is False


def test_adk_provider_complete_raises_not_implemented() -> None:
    """``complete`` must raise ``NotImplementedError`` (fail-closed)."""

    provider = AdkLlmProvider()
    request = LlmRequest(
        model="adk-stub",
        messages=[LlmMessage(role="user", content="hello")],
    )
    import asyncio

    with pytest.raises(NotImplementedError):
        asyncio.run(provider.complete(request))


def test_adk_provider_has_no_capabilities_when_dormant() -> None:
    """A dormant adapter must not advertise any capability flags.

    Other adapters set ``provider.capabilities`` to ``STANDARD_CAPABILITIES``
    after construction. The stub leaves it ``None`` so the orchestrator can
    detect the dormant state without inspecting a vendor name.
    """

    provider = AdkLlmProvider()
    # The base class default is ``None``; the stub never overrides it.
    assert provider.capabilities is None
    assert not isinstance(provider.capabilities, ProviderCapabilities)


def test_is_adk_enabled_defaults_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag is opt-in; unset means the stub stays dormant."""

    monkeypatch.delenv("ADK_ENABLED", raising=False)
    assert is_adk_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "on"])
def test_is_adk_enabled_truthy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Truthy spellings all activate the flag."""

    monkeypatch.setenv("ADK_ENABLED", value)
    assert is_adk_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "random"])
def test_is_adk_enabled_falsy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Anything other than the truthy set keeps the flag off."""

    monkeypatch.setenv("ADK_ENABLED", value)
    assert is_adk_enabled() is False


def test_register_adk_provider_is_noop_when_flag_unset() -> None:
    """The helper must not touch the registry while ``ADK_ENABLED`` is unset."""

    # Sanity: ADK slot is not registered at import time.
    install_builtin_providers()
    unregister_provider(ADK_PROVIDER_NAME)

    registered = register_adk_provider()
    assert registered is False

    # Asking again still no-ops and does not register the slot.
    assert register_adk_provider() is False


def test_register_adk_provider_records_dormant_slot_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the flag is on, the dormant stub is registered under its name."""

    monkeypatch.setenv("ADK_ENABLED", "true")
    install_builtin_providers()
    unregister_provider(ADK_PROVIDER_NAME)

    registered = register_adk_provider()
    assert registered is True

    # A second call is a no-op (the slot is already present, ``replace=False``).
    assert register_adk_provider() is True

    # Cleanup so other tests see a clean registry.
    unregister_provider(ADK_PROVIDER_NAME)