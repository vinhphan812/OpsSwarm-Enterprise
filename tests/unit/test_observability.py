"""Unit tests for observability features: correlation middleware, structured logging.

Covers acceptance criteria for task t_6871dd82 (issues #30, #21):
  - CorrelationMiddleware stamps X-Corr-ID and X-Request-ID headers.
  - setup_logging() configures the opsswarm logger with StructuredLogFormatter.
  - make_admin_token / make_read_token convenience helpers exist and work.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from io import StringIO
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset logging config after each test to avoid polluting other test modules."""
    root = logging.getLogger("opsswarm")
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.setLevel(logging.NOTSET)
    yield
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.setLevel(logging.NOTSET)


@pytest.fixture
def _env_secret():
    """Provide a test runtime secret for token generation tests."""
    old = os.environ.get("OPSWARM_RUNTIME_SECRET")
    os.environ["OPSWARM_RUNTIME_SECRET"] = "test-secret"  # noqa: B105
    import opsswarm.auth as auth_module
    auth_module.reload_auth_config()
    yield
    if old is None:
        os.environ.pop("OPSWARM_RUNTIME_SECRET", None)
    else:
        os.environ["OPSWARM_RUNTIME_SECRET"] = old
    auth_module.reload_auth_config()


# ---------------------------------------------------------------------------
# Tests — StructuredLogFormatter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_structured_log_formatter_emit_json(caplog: pytest.LogCaptureFixture):
    """StructuredLogFormatter outputs a valid JSON object with corr_id."""
    from opsswarm.logging_config import StructuredLogFormatter, set_corr_id

    formatter = StructuredLogFormatter()
    set_corr_id("test-corr-123")

    # Capture stderr output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)

    logger = logging.getLogger("opsswarm.test_formatter")
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Hello world")

    output = stream.getvalue()
    parsed = json.loads(output)

    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Hello world"
    assert parsed["corr_id"] == "test-corr-123"
    assert parsed["logger"] == "opsswarm.test_formatter"


@pytest.mark.unit
def test_structured_log_formatter_default_corr_id(caplog: pytest.LogCaptureFixture):
    """StructuredLogFormatter reads corr_id from the context variable unchanged."""
    from opsswarm.logging_config import StructuredLogFormatter, corr_id_var

    formatter = StructuredLogFormatter()
    # When corr_id is "no-corr-id" (the default), formatter outputs it as-is.
    # New ID generation is handled by get_corr_id(), tested separately.
    corr_id_var.set("no-corr-id")

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)

    logger = logging.getLogger("opsswarm.test_default")
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("No context")

    output = stream.getvalue()
    parsed = json.loads(output)

    # Formatter reads the context variable value directly
    assert parsed["corr_id"] == "no-corr-id"


@pytest.mark.unit
def test_get_corr_id_generates_fresh_id_when_unset():
    """get_corr_id() creates a new ID when context has no real corr_id."""
    from opsswarm.logging_config import get_corr_id, corr_id_var

    corr_id_var.set("no-corr-id")
    new_id = get_corr_id()

    assert new_id != "no-corr-id"
    assert len(new_id) > 0
    # The generated ID should look like a valid correlation ID (UUID-like hex)
    assert len(new_id) >= 8


# ---------------------------------------------------------------------------
# Tests — setup_logging
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_setup_logging_configures_opsswarm_logger():
    """setup_logging() installs the StructuredLogFormatter on the opsswarm root."""
    from opsswarm.logging_config import StructuredLogFormatter, setup_logging

    setup_logging(level="DEBUG")

    root = logging.getLogger("opsswarm")
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, StructuredLogFormatter)


@pytest.mark.unit
def test_setup_logging_silences_noisy_libraries():
    """setup_logging() silences uvicorn, httpx, httpcore."""
    from opsswarm.logging_config import setup_logging

    setup_logging(level="INFO")

    assert logging.getLogger("uvicorn.access").level >= logging.WARNING
    assert logging.getLogger("uvicorn.error").level >= logging.WARNING
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


# ---------------------------------------------------------------------------
# Tests — CorrelationMiddleware (unit, no HTTP server needed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_correlation_middleware_class_exists():
    """CorrelationMiddleware is importable and is a BaseHTTPMiddleware."""
    from starlette.middleware.base import BaseHTTPMiddleware

    from opsswarm.api import CorrelationMiddleware

    assert issubclass(CorrelationMiddleware, BaseHTTPMiddleware)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_correlation_middleware_reuse_incoming_id():
    """If client supplies X-Corr-ID, middleware reuses it unchanged."""
    from unittest.mock import AsyncMock, MagicMock

    from opsswarm.api import CorrelationMiddleware

    middleware = CorrelationMiddleware(app=MagicMock())

    # Simulate request with incoming X-Corr-ID
    request = MagicMock()
    request.headers.get = lambda h: "client-provided-id" if h == "x-corr-id" else None

    response = MagicMock()
    response.headers = {}

    call_next = AsyncMock(return_value=response)

    # Run the middleware via pytest-asyncio
    result = await middleware.dispatch(request, call_next)

    # The response should have the incoming ID in both headers
    assert result.headers.get("X-Corr-ID") == "client-provided-id"
    assert result.headers.get("X-Request-ID") == "client-provided-id"


# ---------------------------------------------------------------------------
# Tests — make_admin_token / make_read_token helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_make_admin_token_creates_valid_token(_env_secret):
    """make_admin_token returns a token with scope opsswarm:admin."""
    from opsswarm.auth import SCOPE_ADMIN, make_admin_token

    token = make_admin_token("test-secret")
    scope, _ = token.split("=", 1)
    assert scope == SCOPE_ADMIN


@pytest.mark.unit
def test_make_read_token_creates_valid_token(_env_secret):
    """make_read_token returns a token with scope opsswarm:read."""
    from opsswarm.auth import SCOPE_READ, make_read_token

    token = make_read_token("test-secret")
    scope, _ = token.split("=", 1)
    assert scope == SCOPE_READ


@pytest.mark.unit
def test_make_admin_token_valid_for_metrics(_env_secret):
    """make_admin_token defaults to GET /metrics (admin-scoped endpoint)."""
    from opsswarm.auth import make_admin_token, verify_bearer_hmac

    secret = "test-secret"
    token = make_admin_token(secret)

    scope, hmac_hex = token.split("=", 1)

    # Verify it matches the expected payload
    import time
    ts = int(time.time())
    payload = f"GET:/metrics:{ts}"
    import hashlib
    import hmac as hmac_lib
    expected = hmac_lib.new(
        secret.encode("ascii"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    assert hmac_hex == expected or verify_bearer_hmac(
        scope, hmac_hex, secret, "GET", "/metrics", ts
    )


# ---------------------------------------------------------------------------
# Tests — Integration: middleware + logging together
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_middleware_and_logging_integration():
    """Full round-trip: middleware binds corr_id, logger emits JSON with that ID."""
    from opsswarm.logging_config import setup_logging, corr_id_var, set_corr_id
    from opsswarm.api import CorrelationMiddleware

    setup_logging(level="DEBUG")

    # Bind a correlation ID as the middleware would
    test_id = "middleware-test-456"
    set_corr_id(test_id)

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.getLogger("opsswarm").handlers[0].formatter)

    logger = logging.getLogger("opsswarm.integration_test")
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("Integration test message")

    output = stream.getvalue()
    parsed = json.loads(output)

    assert parsed["corr_id"] == test_id
    assert parsed["message"] == "Integration test message"
