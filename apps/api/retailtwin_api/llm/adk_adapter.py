"""Stub for ADK multi-agent specialization (#21).

This module exists to fix the *adapter boundary* for an optional Google ADK
integration behind the provider-neutral ``LlmProvider`` interface (ADR 0008,
ADR 0020). It deliberately does **not** import ``google-adk``: the dependency
is gated by a future decision PR and is not part of this preparatory stub.

Disabled by config (``ADK_ENABLED`` default ``false``). To activate, set
``ADK_ENABLED=true`` and provide Google ADK credentials in a follow-up PR.

Per ADR 0042 the orchestrator is unaware of this adapter. Callers must check
``is_configured()`` before instantiating it; if the flag is off the methods
raise ``NotImplementedError`` so a misconfigured production rollout fails
closed instead of silently swapping the canonical provider.
"""

from __future__ import annotations

import os

from .contracts import LlmProvider, LlmRequest, LlmResponse

__all__ = ["AdkLlmProvider", "is_adk_enabled"]


def is_adk_enabled() -> bool:
    """Return whether the ADK adapter is configured for activation.

    Reads the ``ADK_ENABLED`` environment variable. Default ``false``.
    The variable is intentionally not surfaced via ``Settings`` because the
    real adapter is not yet wired and we want zero runtime coupling to the
    process settings today. The flag is consulted only when ``register_adk_provider``
    is called.
    """

    return os.environ.get("ADK_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


class AdkLlmProvider(LlmProvider):
    """Dormant adapter for the optional Google ADK multi-agent path.

    All public methods raise ``NotImplementedError``. ``is_configured()``
    returns ``False`` while the real implementation is not yet shipped. The
    orchestrator must check ``is_configured()`` before calling ``complete``;
    a stub-by-default stance keeps #21 in a documented preparatory state and
    satisfies the owner review on PR #254 (the round-3 "explicitly renamed
    preparatory stub task" framing).
    """

    def is_configured(self) -> bool:
        """Return ``False`` — the stub is never configured.

        The real adapter will override this once ``google-adk`` is added to
        the lockfile (gated by a future decision PR) and the specialized
        orchestrator paths (Observer/Investigator/Planner/Simulator/Verifier)
        are wired against the real supported API.
        """

        return False

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Not implemented — the stub never runs a real ADK call."""

        raise NotImplementedError(
            "AdkLlmProvider is a stub for #21. "
            "Activate via ADK_ENABLED=true plus a real google-adk pin "
            "(see ADR 0042)."
        )

    async def aclose(self) -> None:  # pragma: no cover - trivially safe no-op
        """Hook for symmetry with other adapters; no resources to release."""

        return None