"""Coverage tests for opsswarm.logging_config.

All 43 statements in logging_config.py are uncovered. These tests provide
full coverage by exercising setup_logging, StructuredLogFormatter, get_corr_id,
set_corr_id, and bind_request_context.
"""

import logging
import json
import sys
import pytest

from opsswarm.logging_config import (
    StructuredLogFormatter,
    setup_logging,
    get_corr_id,
    set_corr_id,
    bind_request_context,
    corr_id_var,
)


# -----------------------------------------------------------------------
# StructuredLogFormatter
# -----------------------------------------------------------------------

def test_formatter_includes_corr_id(caplog):
    """StructuredLogFormatter includes corr_id in JSON output."""
    formatter = StructuredLogFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "corr_id" in parsed
    assert parsed["message"] == "hello"
    assert parsed["level"] == "INFO"


def test_formatter_includes_exception_info(caplog):
    """StructuredLogFormatter includes exc_type and exc_msg when exc_info is present."""
    formatter = StructuredLogFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg="failed",
        args=(),
        exc_info=exc_info,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["exc_type"] == "ValueError"
    assert "test error" in parsed["exc_msg"]


def test_formatter_extra_fields(caplog):
    """StructuredLogFormatter includes issue_number, run_id, agent_profile when present."""
    formatter = StructuredLogFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    record.issue_number = 42
    record.run_id = "run-abc"
    record.agent_profile = "incident-manager"
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["issue_number"] == 42
    assert parsed["run_id"] == "run-abc"
    assert parsed["agent_profile"] == "incident-manager"


def test_formatter_extra_fields_omitted_when_absent():
    """StructuredLogFormatter omits extra fields when not present on record."""
    formatter = StructuredLogFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "issue_number" not in parsed
    assert "run_id" not in parsed
    assert "agent_profile" not in parsed


# -----------------------------------------------------------------------
# setup_logging
# -----------------------------------------------------------------------

def test_setup_logging_configures_root_logger(caplog):
    """setup_logging configures the opsswarm root logger with a structured handler."""
    setup_logging(level="DEBUG")

    root = logging.getLogger("opsswarm")
    assert root.level == logging.DEBUG
    assert len(root.handlers) >= 1
    handler = root.handlers[0]
    assert isinstance(handler.formatter, StructuredLogFormatter)


def test_setup_logging_accepts_info_level(caplog):
    """setup_logging(level='INFO') sets the root logger to INFO."""
    setup_logging(level="INFO")
    root = logging.getLogger("opsswarm")
    assert root.level == logging.INFO


def test_setup_logging_invalid_level_uses_default(caplog):
    """setup_logging with unknown level falls back to INFO."""
    setup_logging(level="NOT_A_REAL_LEVEL")
    root = logging.getLogger("opsswarm")
    # getattr fallback → logging.INFO
    assert root.level == logging.INFO


def test_setup_logging_silences_third_party_loggers(caplog):
    """setup_logging silences noisy third-party loggers (uvicorn, httpx, etc.)."""
    setup_logging(level="INFO")

    # These loggers should be set to WARNING
    for lib in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logger = logging.getLogger(lib)
        assert logger.level == logging.WARNING


# -----------------------------------------------------------------------
# get_corr_id
# -----------------------------------------------------------------------

def test_get_corr_id_returns_existing_when_set(caplog):
    """get_corr_id() returns the current context value when already bound."""
    set_corr_id("existing-id-123")
    assert get_corr_id() == "existing-id-123"


def test_get_corr_id_generates_new_when_unset(caplog):
    """get_corr_id() generates a new correlation ID when no-corr-id is the default."""
    # Reset to default
    corr_id_var.set("no-corr-id")
    cid = get_corr_id()
    assert cid != "no-corr-id"
    assert len(cid) > 0


# -----------------------------------------------------------------------
# set_corr_id
# -----------------------------------------------------------------------

def test_set_corr_id_updates_context(caplog):
    """set_corr_id() binds a value to the corr_id context variable."""
    set_corr_id("custom-corr-id")
    assert corr_id_var.get() == "custom-corr-id"


# -----------------------------------------------------------------------
# bind_request_context
# -----------------------------------------------------------------------

def test_bind_request_context_returns_and_sets_cid(caplog):
    """bind_request_context() generates a CID, binds it, and returns it."""
    cid = bind_request_context()
    assert cid != ""
    assert len(cid) > 0
    assert corr_id_var.get() == cid
