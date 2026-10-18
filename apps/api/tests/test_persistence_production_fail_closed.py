"""Tests for the production fail-closed guard in ``persistence.py``.

ADR-0024 requires that a Cloud Run instance with ``APP_ENV=production``
refuse to start when ``LIVE_TWIN_BACKEND`` is missing or unknown,
rather than silently falling back to in-process memory where agent
state would be lost on the next deploy.
"""

from __future__ import annotations

import pytest

from retailtwin_api.persistence import get_persistence
from retailtwin_api.settings import Settings


class _FakeSettings:
    """Minimal Settings stand-in for factory tests."""

    def __init__(
        self,
        live_twin_backend: str = "memory",
        app_env: str = "development",
        store_id: str = "store-001",
        google_cloud_project: str | None = None,
    ) -> None:
        self.live_twin_backend = live_twin_backend  # type: ignore[attr-defined]
        self.app_env = app_env  # type: ignore[attr-defined]
        self.is_production = app_env == "production"  # type: ignore[attr-defined]
        self.store_id = store_id  # type: ignore[attr-defined]
        self.google_cloud_project = google_cloud_project  # type: ignore[attr-defined]


class TestPersistenceProductionFailClosed:
    """Production (``APP_ENV=production``) is fail-closed on bad backend config."""

    @pytest.mark.parametrize(
        "backend",
        [
            "",
            "unknown",
            "MEMORY",
            "FIRESTORE",
            "dynamodb",
        ],
    )
    def test_production_rejects_unknown_backend(self, backend: str) -> None:
        settings = _FakeSettings(live_twin_backend=backend, app_env="production")
        with pytest.raises(ValueError) as exc_info:
            get_persistence(settings)
        msg = str(exc_info.value)
        assert "production" in msg.lower() or "not supported" in msg.lower()

    def test_production_rejects_memory_without_store_view_fn(self) -> None:
        """memory backend in production is rejected even without store_view_fn."""
        settings = _FakeSettings(live_twin_backend="memory", app_env="production")
        with pytest.raises(ValueError) as exc_info:
            get_persistence(settings)
        # The production guard fires before the store_view_fn check.
        assert "production" in str(exc_info.value).lower()

    def test_production_rejects_memory_with_store_view_fn(self) -> None:
        """Even with store_view_fn, memory is not allowed in production."""
        settings = _FakeSettings(live_twin_backend="memory", app_env="production")
        from unittest.mock import patch
        with patch("retailtwin_api.simulation.SimulationRepository._seed"):
            with pytest.raises(ValueError) as exc_info:
                get_persistence(settings, store_view_fn=lambda: None)
        assert "production" in str(exc_info.value).lower()

    def test_production_accepts_firestore(self) -> None:
        """The only valid production value is 'firestore'."""
        settings = _FakeSettings(live_twin_backend="firestore", app_env="production")
        # Should not raise; returns DurableAdapters with Firestore adapters.
        adapters = get_persistence(settings)
        assert adapters.activation_ledger.__class__.__name__ == "FirestoreActivationLedger"
        assert adapters.decisions.__class__.__name__ == "FirestoreDecisionSource"

    def test_production_rejects_fixture(self) -> None:
        """fixture backend is not allowed in production (read-only, no durable state)."""
        settings = _FakeSettings(live_twin_backend="fixture", app_env="production")
        with pytest.raises(ValueError) as exc_info:
            get_persistence(settings)
        assert "production" in str(exc_info.value).lower()


class TestPersistenceNonProduction:
    """Non-production environments (development, test) are warn-closed."""

    def test_development_unknown_backend_warns_and_raises(self) -> None:
        settings = _FakeSettings(live_twin_backend="unknown-backend", app_env="development")
        with pytest.raises(ValueError) as exc_info:
            get_persistence(settings)
        assert "unknown" in str(exc_info.value).lower()

    def test_memory_backend_requires_store_view_fn(self) -> None:
        settings = _FakeSettings(live_twin_backend="memory", app_env="development")
        with pytest.raises(ValueError) as exc_info:
            get_persistence(settings)
        assert "store_view_fn" in str(exc_info.value)

    def test_memory_backend_with_store_view_fn_succeeds(self) -> None:
        """memory backend with a valid store_view_fn returns a SimulationRepository."""
        settings = _FakeSettings(live_twin_backend="memory", app_env="development")
        # SimulationRepository calls store_view_fn() and accesses .products etc.
        # Patch SimulationRepository.__init__ to skip the seed call.
        from unittest.mock import patch
        with patch("retailtwin_api.simulation.SimulationRepository._seed"):
            adapters = get_persistence(settings, store_view_fn=lambda: None)
        assert adapters.simulations.__class__.__name__ == "SimulationRepository"

    def test_fixture_backend_returns_unavailable_adapters(self) -> None:
        settings = _FakeSettings(live_twin_backend="fixture", app_env="development")
        adapters = get_persistence(settings)
        assert adapters.decisions.available is False
        assert adapters.simulations.available is False
