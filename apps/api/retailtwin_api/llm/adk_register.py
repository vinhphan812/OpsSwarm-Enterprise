"""Registration helper for the optional ADK adapter (#21).

When ``ADK_ENABLED`` is unset (default) this is a no-op — the canonical
``vertex_gemini`` / ``fake`` / ``openai_compatible`` adapters stay registered
without an ADK entry. When the flag is on the helper still only registers a
*dormant* builder that returns ``AdkLlmProvider()``, because the real
``google-adk`` integration is gated by a future decision PR (ADR 0042).
"""

from __future__ import annotations

import logging

from .adk_adapter import AdkLlmProvider, is_adk_enabled
from .factory import _REGISTRY, register_provider
from .contracts import STANDARD_CAPABILITIES

_logger = logging.getLogger(__name__)

ADK_PROVIDER_NAME = "adk_specialized"


def _build_adk(config) -> AdkLlmProvider:  # type: ignore[no-untyped-def]
    """Builder invoked by ``create_provider`` when ``LLM_PROVIDER=adk_specialized``.

    Today this returns the stub. A future PR may override the builder with
    the real ``google-adk`` adapter while keeping this registration name,
    so callers do not need to be edited.
    """

    return AdkLlmProvider()


def register_adk_provider(*, replace: bool = False) -> bool:
    """Register the dormant ADK adapter behind the ``LlmProvider`` boundary.

    Returns ``True`` if the adapter was registered, ``False`` when the flag is
    off and the call is a no-op. The helper is idempotent: if the slot is
    already occupied by the dormant builder a subsequent call is a no-op,
    not a duplicate-registration error. Pass ``replace=True`` to force a
    rebind (rare; intended for tests).
    """

    if not is_adk_enabled():
        _logger.debug(
            "register_adk_provider: ADK_ENABLED is unset; no-op (per ADR 0042)."
        )
        return False
    if ADK_PROVIDER_NAME in _REGISTRY and not replace:
        _logger.debug(
            "register_adk_provider: %s already registered; no-op.",
            ADK_PROVIDER_NAME,
        )
        return True
    register_provider(
        ADK_PROVIDER_NAME,
        _build_adk,
        STANDARD_CAPABILITIES,
        replace=replace,
    )
    _logger.info(
        "register_adk_provider: registered dormant ADK adapter (stub; ADR 0042)."
    )
    return True


__all__ = ["ADK_PROVIDER_NAME", "register_adk_provider"]