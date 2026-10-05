# Pytest configuration and shared fixtures
import os


# ----------------------------------------------------------------------
# Session-level auth setup (runs before any test module imports)
# Metrics tests use a module-level TestClient that loads before any test
# functions run, so auth must be configured at session scope.
# ----------------------------------------------------------------------
def pytest_sessionstart(session):
    os.environ.setdefault("OPSWARM_RUNTIME_SECRET", "test-secret")

    # Suppress GitHubClient fail-closed validation so opsswarm.api can be
    # imported safely in tests that mock gh/engine/oc after import.
    try:
        from opsswarm.github_client import GitHubClient

        _orig_init = GitHubClient.__init__

        def _patched_init(self, *args, **kwargs):
            # Skip the repo/allowed-origins fail-closed checks; mock the client
            self._patched = True

        GitHubClient.__init__ = _patched_init
    except ImportError:
        pass

    try:
        import opsswarm.auth as _auth_mod

        _auth_mod.reload_auth_config()
    except ImportError:
        pass  # opsswarm not installed in conftest env


# ----------------------------------------------------------------------
# Per-test teardown: clear shared auth state to avoid cross-test pollution.
# The anti-replay store and monitoring rate limiter are module-level singletons.
# ----------------------------------------------------------------------
def pytest_runtest_teardown(item, nextitem):
    """Reset auth module state after every test to avoid cross-test pollution."""
    try:
        import opsswarm.auth as _auth_mod
        _auth_mod._monitoring_limiter._hits.clear()
        _auth_mod.reset_replay_store()
    except (ImportError, AttributeError):
        pass


# Pytest markers for test layer categorization
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Pure function tests with no I/O")
    config.addinivalue_line("markers", "contract: Skill contract validation tests")
    config.addinivalue_line("markers", "integration: Multi-component tests with fakes")
    config.addinivalue_line("markers", "e2e: Full system tests with real HTTP/process")
    config.addinivalue_line("markers", "fault: Fault injection and recovery tests")
    config.addinivalue_line("markers", "security: Authorization and authentication tests")
    config.addinivalue_line("markers", "smoke: Quick sanity checks")
    config.addinivalue_line("markers", "slow: Long-running tests")
