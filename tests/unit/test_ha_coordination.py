"""Unit tests for the HA coordination runtime helpers (ADR-030).

These cover the code paths that ``opsswarm/auth.py`` and ``opsswarm/ha_db.py``
add for HA mode: the PostgreSQL-backed rate limiter, the rate-limit pruner
task, and the configuration lookup that decides whether HA is active.

The PostgreSQL driver is never imported here: the HA database module is
injected as a stub so the tests run without a database and without the
``psycopg`` package installed.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import opsswarm
import opsswarm.auth as auth_module
from opsswarm.rate_limit_errors import (
    RateLimitInfrastructureError,
    RateLimitProgrammingError,
)

# Sentinel for "the parent package has no such attribute", distinct from None.
_MISSING = object()


@contextmanager
def _patched_shared_store(stub):
    """Substitute the shared store so the stub is what the code actually sees.

    ``opsswarm.auth`` resolves the store with a package-relative import
    (``from . import ha_db``).  That form reads the attribute already bound on
    the parent package, so patching ``sys.modules`` alone is not enough once
    the real module has been imported by an earlier test: the real module
    would win and the stub would never be exercised.

    Patch both the ``sys.modules`` entry and the parent-package attribute so
    the substitution holds regardless of import form and of test ordering.

    Passing ``None`` simulates the module being unavailable: the
    ``sys.modules`` entry must be ``None`` and the parent attribute removed,
    because that combination is what makes the import raise ``ImportError``.
    """
    if stub is None:
        saved = getattr(opsswarm, "ha_db", _MISSING)
        with patch.dict(sys.modules, {"opsswarm.ha_db": None}):
            if saved is not _MISSING:
                delattr(opsswarm, "ha_db")
            try:
                yield None
            finally:
                if saved is not _MISSING:
                    opsswarm.ha_db = saved
        return

    with (
        patch.dict(sys.modules, {"opsswarm.ha_db": stub}),
        patch.object(opsswarm, "ha_db", stub, create=True),
    ):
        yield stub


@pytest.fixture(autouse=True)
def _reset_pruner_state():
    """Keep the module-level pruner task and config cache isolated."""
    auth_module.stop_rate_limit_pruner()
    auth_module._ha_cfg_cache = None
    yield
    auth_module.stop_rate_limit_pruner()
    auth_module._ha_cfg_cache = None


class TestHaConfigLookup:
    """``_ha_config`` must read the deployed configuration, not the defaults."""

    def test_uses_loaded_configuration(self):
        with patch("opsswarm.auth.load_config", return_value={"ha": {"enabled": True}}) as load:
            assert auth_module._ha_config()["enabled"] is True
        load.assert_called_once()

    def test_caches_between_calls(self):
        with patch("opsswarm.auth.load_config", return_value={"ha": {"enabled": True}}) as load:
            auth_module._ha_config()
            auth_module._ha_config()
        assert load.call_count == 1

    def test_cache_is_cleared_when_environment_is_reloaded(self):
        with patch("opsswarm.auth.load_config", return_value={"ha": {"enabled": True}}) as load:
            auth_module._ha_config()
            auth_module.reload_auth_config()
            auth_module._ha_config()
        assert load.call_count == 2

    def test_missing_section_falls_back_to_defaults(self):
        with patch("opsswarm.auth.load_config", return_value={}):
            cfg = auth_module._ha_config()
        assert cfg["enabled"] is False
        assert cfg["rate_limit_table_enabled"] is False


class TestPgRateLimiter:
    """``_PgRateLimiter`` falls back to the in-memory limiter unless HA is on."""

    async def test_falls_back_to_in_memory_when_ha_disabled(self):
        limiter = auth_module._PgRateLimiter(max_requests=5, window_seconds=60)
        with patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": False}):
            allowed, retry_after = await limiter.is_allowed("source-1")
        assert allowed is True
        assert retry_after == 0

    async def test_uses_postgres_when_enabled(self):
        limiter = auth_module._PgRateLimiter(max_requests=5, window_seconds=60)
        stub = MagicMock()
        stub.check_rate_limit_pg = AsyncMock(return_value=(False, 42))
        with (
            patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": True}),
            _patched_shared_store(stub),
        ):
            allowed, retry_after = await limiter.is_allowed("source-2")
        assert allowed is False
        assert retry_after == 42
        stub.check_rate_limit_pg.assert_awaited_once_with("source-2", 5, 60)

    async def test_stub_is_used_even_after_the_real_module_was_imported(self):
        """The substitution must hold regardless of test ordering.

        ``opsswarm.auth`` resolves the store with ``from . import ha_db``,
        which reads the attribute bound on the parent package.  Once any
        earlier test has imported the real module, a ``sys.modules``-only
        patch is silently ignored and the real store would be called instead
        of the stub.

        The real module is not imported here - it needs the optional ``ha``
        extra, and this file never imports the driver - so a stand-in is bound
        to the parent package instead.  That reproduces the same state: the
        attribute exists, so a ``sys.modules``-only patch would no longer be
        enough.
        """
        previously_imported = MagicMock()
        previously_imported.check_rate_limit_pg = AsyncMock(
            side_effect=AssertionError("the previously imported store must not be called")
        )

        limiter = auth_module._PgRateLimiter(max_requests=5, window_seconds=60)
        stub = MagicMock()
        stub.check_rate_limit_pg = AsyncMock(return_value=(False, 42))
        with (
            patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": True}),
            patch.object(opsswarm, "ha_db", previously_imported, create=True),
            _patched_shared_store(stub),
        ):
            allowed, retry_after = await limiter.is_allowed("source-stub")

        assert (allowed, retry_after) == (False, 42)
        stub.check_rate_limit_pg.assert_awaited_once_with("source-stub", 5, 60)
        previously_imported.check_rate_limit_pg.assert_not_awaited()

    async def test_falls_back_to_in_memory_when_postgres_raises(self):
        """An infrastructure outage falls back to the bounded local limit."""
        limiter = auth_module._PgRateLimiter(max_requests=5, window_seconds=60)
        with (
            patch(
                "opsswarm.auth._ha_config",
                return_value={"rate_limit_table_enabled": True},
            ),
            _patched_shared_store(
                MagicMock(
                    check_rate_limit_pg=AsyncMock(
                        side_effect=RateLimitInfrastructureError("unreachable")
                    )
                )
            ),
        ):
            allowed, retry_after = await limiter.is_allowed("source-3")
        assert allowed is True
        assert retry_after == 0

    async def test_programming_error_is_not_masked(self):
        """A schema defect propagates instead of falling back (Issue #127)."""
        limiter = auth_module._PgRateLimiter(max_requests=5, window_seconds=60)
        with (
            patch(
                "opsswarm.auth._ha_config",
                return_value={"rate_limit_table_enabled": True},
            ),
            _patched_shared_store(
                MagicMock(
                    check_rate_limit_pg=AsyncMock(
                        side_effect=RateLimitProgrammingError("schema is not usable")
                    )
                )
            ),
        ):
            with pytest.raises(RateLimitProgrammingError):
                await limiter.is_allowed("source-4")


class TestMonitoringRateLimit:
    """The monitoring rate limiters honour the HA feature flag."""

    async def test_async_uses_in_memory_when_disabled(self):
        with patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": False}):
            allowed, retry_after = await auth_module.check_monitoring_rate_limit_async("ip-1")
        assert allowed is True
        assert retry_after == 0

    async def test_async_uses_postgres_when_enabled(self):
        stub = MagicMock()
        stub.check_rate_limit_pg = AsyncMock(return_value=(True, 0))
        with (
            patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": True}),
            _patched_shared_store(stub),
        ):
            allowed, _ = await auth_module.check_monitoring_rate_limit_async("ip-2")
        assert allowed is True
        stub.check_rate_limit_pg.assert_awaited_once()

    async def test_sync_entry_point_no_longer_exists(self):
        """The misleading synchronous entry point was removed (Issue #127).

        It used to return the in-memory verdict while the operator believed
        the shared PostgreSQL limiter was active.  A caller must not be able
        to reach in-memory semantics by accident, so the function is gone
        rather than kept as a trap.
        """
        assert not hasattr(auth_module, "check_monitoring_rate_limit")

    async def test_async_uses_in_memory_limiter_when_disabled(self):
        with patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": False}):
            allowed, retry_after = await auth_module.check_monitoring_rate_limit_async("ip-3")
        assert allowed is True
        assert retry_after == 0


class TestRateLimitPruner:
    """The pruner task starts only when HA rate limiting is enabled."""

    def test_does_not_start_when_disabled(self):
        with patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": False}):
            auth_module.start_rate_limit_pruner()
        assert auth_module._rate_limit_prune_task is None

    async def test_starts_when_enabled(self):
        with patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": True}):
            auth_module.start_rate_limit_pruner()
            task = auth_module._rate_limit_prune_task
            assert task is not None
            auth_module.stop_rate_limit_pruner()
            assert auth_module._rate_limit_prune_task is None

    async def test_start_is_idempotent(self):
        with patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": True}):
            auth_module.start_rate_limit_pruner()
            first = auth_module._rate_limit_prune_task
            auth_module.start_rate_limit_pruner()
            assert auth_module._rate_limit_prune_task is first
            auth_module.stop_rate_limit_pruner()

    def test_stop_without_start_is_safe(self):
        auth_module.stop_rate_limit_pruner()
        assert auth_module._rate_limit_prune_task is None

    async def test_pruner_loop_prunes_expired_buckets(self):
        stub = MagicMock()
        stub.prune_expired_rate_limits = AsyncMock(return_value=2)
        with (
            patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": True}),
            _patched_shared_store(stub),
            patch.object(auth_module.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])),
        ):
            # The loop breaks out on cancellation instead of propagating it.
            await auth_module._start_rate_limit_pruner()
        stub.prune_expired_rate_limits.assert_awaited_once()

    async def test_pruner_survives_a_pruning_error(self):
        stub = MagicMock()
        stub.prune_expired_rate_limits = AsyncMock(side_effect=RuntimeError("db down"))
        with (
            patch("opsswarm.auth._ha_config", return_value={"rate_limit_table_enabled": True}),
            _patched_shared_store(stub),
            patch.object(auth_module.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError])),
        ):
            await auth_module._start_rate_limit_pruner()
        stub.prune_expired_rate_limits.assert_awaited_once()
