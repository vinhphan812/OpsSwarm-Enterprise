# Pytest configuration and shared fixtures
import os


# ----------------------------------------------------------------------
# Session-level auth setup (runs before any test module imports)
# Metrics tests use a module-level TestClient that loads before any test
# functions run, so auth must be configured at session scope.
# ----------------------------------------------------------------------
def pytest_sessionstart(session):
    os.environ.setdefault("OPSWARM_RUNTIME_SECRET", "test-secret")

    # Provide minimal env so opsswarm.api's module-level GitHubClient(...)
    # construction does not fail with a ValueError (fail-closed on empty repo
    # and no approved origins).  The real gh object is fully constructed; we
    # replace it with a dummy immediately after so that tests that import
    # opsswarm.api get a harmless no-op instead of a live client.
    # Patching api.gh (instead of GitHubClient.__init__) keeps the real
    # GitHubClient.__init__ intact so the 62 tests that directly instantiate
    # GitHubClient(...) still receive a fully-formed client with .repo /
    # .base_url / .client attributes.
    os.environ.setdefault("GITHUB_TOKEN", "test-token")
    os.environ.setdefault("GITHUB_REPO", "test/test-repo")
    os.environ.setdefault("OPSWARM_GITHUB_ORIGINS", "https://api.github.com")
    os.environ.setdefault("OPSWARM_OPENCLAW_BIN", "openclaw")
    os.environ.setdefault("OPSWARM_OPENCLAW_TIMEOUT", "600")
    os.environ.setdefault("OPSWARM_DATA_DIR", "runtime-data")

    try:
        import opsswarm.api as _api_mod

        class _DummyGH:
            """Minimal stand-in for GitHubClient — satisfies attribute access."""

            _patched = True

        _api_mod.gh = _DummyGH()
    except ImportError:
        pass  # opsswarm not installed in conftest env

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
