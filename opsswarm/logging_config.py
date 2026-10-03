"""opsswarm.logging_config — Structured JSON logging with correlation IDs.

All opsswarm loggers are configured here so operators can grep logs by
correlation ID without needing to parse unstructured text.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from typing import Any

from .errors import new_correlation_id

# ── Context variable ──────────────────────────────────────────────────────────
# Stamped on every log record via LogRecordmanufacture; available throughout
# the current async request/task boundary without passing ctx explicitly.
corr_id_var: ContextVar[str] = ContextVar("corr_id", default="no-corr-id")

# ── JSON log formatter ────────────────────────────────────────────────────────


class StructuredLogFormatter(logging.Formatter):
    """Emit one JSON object per log line with corr_id baked in."""

    def format(self, record: logging.LogRecord) -> str:
        # Stamp corr_id from context
        corr_id = corr_id_var.get()
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "corr_id": corr_id,
        }
        # Include standard fields when present
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc_msg"] = str(record.exc_info[1]) if record.exc_info[1] else None
        if hasattr(record, "issue_number"):
            payload["issue_number"] = record.issue_number
        if hasattr(record, "run_id"):
            payload["run_id"] = record.run_id
        if hasattr(record, "agent_profile"):
            payload["agent_profile"] = record.agent_profile
        return json.dumps(payload, default=str)


# ── Convenience helpers ───────────────────────────────────────────────────────


def setup_logging(*, level: str = "INFO") -> None:
    """Configure the root opsswarm logger with structured JSON output.

    Call once at application startup (before any other module imports a logger).
    """
    root = logging.getLogger("opsswarm")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing handlers (e.g. defaults from library loggers)
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(StructuredLogFormatter())
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for lib in ("uvicorn.access", "uvicorn.error", "httpx", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_corr_id() -> str:
    """Return the current correlation ID (create one if none in context)."""
    val = corr_id_var.get()
    if val == "no-corr-id":
        return new_correlation_id()
    return val


def set_corr_id(value: str) -> Token[str]:
    """Bind a specific correlation ID and return its reset token."""
    return corr_id_var.set(value)


def reset_corr_id(token: Token[str]) -> None:
    """Restore the correlation context that was active before a request."""
    corr_id_var.reset(token)


def bind_request_context() -> str:
    """Generate and bind a fresh correlation ID for a new request.

    Returns the ID so callers can include it in response headers.
    """
    cid = new_correlation_id()
    corr_id_var.set(cid)
    return cid
