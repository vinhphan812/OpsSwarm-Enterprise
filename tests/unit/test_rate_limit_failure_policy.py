"""Rate-limit failure policy for the shared (PostgreSQL) store (Issue #127).

The shared limiter used to fail *open*: any database exception produced
"allowed".  A transient outage therefore disabled the distributed limit for
every identity with only a log line as evidence, and a schema defect was
masked at runtime.

These tests pin the replacement policy:

- an infrastructure outage (the database cannot be reached) throttles the
  caller through the bounded local limit, logs a warning, and increments the
  degraded-mode metric;
- a programming or schema defect propagates instead of being masked;
- with the shared limiter disabled the behaviour is unchanged;
- the failure never leaks database internals to the caller.

The tests do not import ``psycopg`` or ``opsswarm.ha_db``.  The PostgreSQL
driver is an optional dependency (the ``ha`` extra), and the base package must
be testable without it, so the shared store is injected as a stub exactly as
``tests/unit/test_ha_coordination.py`` does.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import opsswarm
import opsswarm.auth as auth_module
from opsswarm.metrics import metrics
from opsswarm.rate_limit_errors import (
    RateLimitInfrastructureError,
    RateLimitProgrammingError,
)

# Sentinel for "the parent package has no such attribute", distinct from None.
_MISSING = object()


def _reset_limiter() -> None:
    auth_module._monitoring_limiter._hits.clear()
    auth_module._monitoring_limiter._last_access.clear()
    auth_module._monitoring_limiter._max_buckets = 1000


def _degraded_count(reason: str) -> int:
    return metrics.rate_limit_degraded.get(reason, 0)


def _stub_shared_store(side_effect: BaseException) -> AsyncMock:
    """Return a stub for the shared store that raises ``side_effect``."""
    stub = AsyncMock()
    stub.check_rate_limit_pg = AsyncMock(side_effect=side_effect)
    return stub


@contextmanager
def _patched_shared_store(stub: AsyncMock):
    """Patch the shared store into place so the stub is what the code sees.

    ``opsswarm.auth`` resolves the store with a package-relative import
    (``from . import ha_db``).  That form reads the attribute already bound on
    the parent package, so patching ``sys.modules`` alone is not enough once
    the real module has been imported by an earlier test: the real module
    would win and the stub would never be exercised.

    Patch both the ``sys.modules`` entry and the parent-package attribute so
    the substitution is effective regardless of import form and of test
    ordering.

    Passing ``None`` simulates the module being unavailable (the optional
    ``ha`` extra is not installed).  In that case the ``sys.modules`` entry
    must be ``None`` and the parent attribute must be removed, because that
    combination is what makes the import raise ``ImportError`` - the same
    failure production sees.
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


class TestSharedRateLimitFailurePolicy:
    """The shared store never silently returns "allowed"."""

    async def test_infrastructure_outage_falls_back_to_the_bounded_limit(self):
        """The caller is throttled by the bounded local limit, not waved through."""
        _reset_limiter()
        auth_module._rate_limit_fallback._hits.clear()
        auth_module._rate_limit_fallback._last_access.clear()
        auth_module._rate_limit_fallback._max_buckets = 1000
        # A deliberately tiny local quota: the fallback must be stricter than
        # the shared quota, so exhausting it blocks the caller.
        auth_module._rate_limit_fallback._max = 1
        try:
            stub = _stub_shared_store(RateLimitInfrastructureError("unreachable"))
            with (
                patch(
                    "opsswarm.auth._ha_config",
                    return_value={"rate_limit_table_enabled": True},
                ),
                _patched_shared_store(stub),
            ):
                allowed_first, _ = await auth_module.check_monitoring_rate_limit_async("ip-a")
                allowed_second, retry_after = await auth_module.check_monitoring_rate_limit_async("ip-a")
        finally:
            auth_module._rate_limit_fallback._max = 5

        assert allowed_first is True
        assert allowed_second is False, "the bounded local fallback must throttle the caller"
        assert retry_after > 0

    async def test_infrastructure_outage_increments_degraded_metric(self):
        """The degraded mode is observable in the metrics endpoint."""
        before = _degraded_count("infrastructure")

        stub = _stub_shared_store(RateLimitInfrastructureError("unreachable"))
        with (
            patch(
                "opsswarm.auth._ha_config",
                return_value={"rate_limit_table_enabled": True},
            ),
            _patched_shared_store(stub),
        ):
            await auth_module.check_monitoring_rate_limit_async("ip-b")

        assert _degraded_count("infrastructure") == before + 1
        assert (
            'opsswarm_rate_limit_degraded_total{reason="infrastructure"}' in metrics.to_prometheus()
        )

    async def test_programming_error_propagates_and_is_counted(self):
        """A deployment defect propagates and is recorded as degraded."""
        before = _degraded_count("programming")

        stub = _stub_shared_store(RateLimitProgrammingError("schema is not usable"))
        with (
            patch(
                "opsswarm.auth._ha_config",
                return_value={"rate_limit_table_enabled": True},
            ),
            _patched_shared_store(stub),
        ):
            with pytest.raises(RateLimitProgrammingError):
                await auth_module.check_monitoring_rate_limit_async("ip-c")

        assert _degraded_count("programming") == before + 1

    def test_api_response_for_database_failure_is_sanitised(self):
        """Raw database exceptions never appear in a caller-visible body."""
        import opsswarm.api as api_module

        stub = _stub_shared_store(
            RateLimitProgrammingError(
                "password=secret db.internal.example:5432 schema missing"
            )
        )
        with (
            patch(
                "opsswarm.auth._ha_config",
                return_value={"rate_limit_table_enabled": True},
            ),
            _patched_shared_store(stub),
            patch.object(
                api_module,
                "_get_real_client_ip",
                return_value="203.0.113.7",
            ),
            patch.object(
                api_module.auth_module,
                "_probe_scope_from_bearer",
                AsyncMock(return_value=None),
            ),
            TestClient(api_module.app, raise_server_exceptions=False) as client,
        ):
            response = client.post("/hooks/monitoring", json={"ping": True})

        assert response.status_code == 500
        assert response.json() == {"detail": "Rate limiting is unavailable"}
        for secret in ("password", "secret", "db.internal.example", "5432", "schema missing"):
            assert secret not in response.text

    async def test_shared_limiter_disabled_is_unchanged(self):
        """With the shared limiter disabled the in-memory limiter governs."""
        _reset_limiter()
        with patch(
            "opsswarm.auth._ha_config",
            return_value={"rate_limit_table_enabled": False},
        ):
            allowed, retry_after = await auth_module.check_monitoring_rate_limit_async("ip-d")
        assert allowed is True
        assert retry_after == 0

    async def test_infrastructure_outage_logs_a_warning(self, caplog):
        """The fallback decision is logged at warning level."""
        stub = _stub_shared_store(RateLimitInfrastructureError("unreachable"))
        with (
            patch(
                "opsswarm.auth._ha_config",
                return_value={"rate_limit_table_enabled": True},
            ),
            _patched_shared_store(stub),
        ):
            with caplog.at_level(logging.WARNING, logger="opsswarm.auth"):
                await auth_module.check_monitoring_rate_limit_async("ip-e")

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "the degraded mode must be logged at warning level"
        assert any("RateLimitInfrastructureError" in r.message for r in warnings)

    async def test_missing_driver_falls_back_instead_of_raising(self):
        """A missing PostgreSQL driver degrades the store, it does not break it."""
        _reset_limiter()
        with (
            patch(
                "opsswarm.auth._ha_config",
                return_value={"rate_limit_table_enabled": True},
            ),
            _patched_shared_store(None),
        ):
            allowed, retry_after = await auth_module.check_monitoring_rate_limit_async("ip-f")
        assert allowed is True
        assert retry_after == 0


class TestNoSyncRateLimitEntrypoint:
    """The misleading synchronous entry point is gone."""

    def test_sync_entry_point_is_removed(self):
        assert not hasattr(auth_module, "check_monitoring_rate_limit")

    def test_api_module_does_not_import_it(self):
        """``opsswarm.api`` must not re-export the removed function."""
        import opsswarm.api as api_module

        assert not hasattr(api_module, "check_monitoring_rate_limit")

    def test_api_module_has_no_unused_imports(self):
        """``ruff --select=F401`` is clean for ``opsswarm/api.py``."""
        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "opsswarm/api.py",
                "--select=F401",
                "--output-format=concise",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout
