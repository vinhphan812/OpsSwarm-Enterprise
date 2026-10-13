"""Production middleware: structured logging, correlation ID, and safe error responses."""

import logging
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


def _configure_json_logging() -> None:
    """Configure structured JSON logging once at module import time.

    Uses sys.stderr (StreamHandler default) so pytest capsys captures stdout
    separately from application logs.  In Cloud Run both streams go to the
    same container stdout; the Cloud Logging agent picks up structured JSON
    from whichever stream is used.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # Already configured (e.g., by a test fixture).

    handler = logging.StreamHandler()  # defaults to sys.stderr
    handler.setFormatter(JsonFormatter())

    # retailtwin_api-level logs — propagate=True so pytest caplog can capture
    # child loggers while the handler still formats JSON for Cloud Logging.
    retailtwin_api_logger = logging.getLogger("retailtwin_api")
    retailtwin_api_logger.setLevel(logging.INFO)
    retailtwin_api_logger.addHandler(handler)
    retailtwin_api_logger.propagate = True

    # Quiet uvicorn (it is very chatty)
    for name in ("uvicorn", "uvicorn.access"):
        l = logging.getLogger(name)
        l.setLevel(logging.WARNING)
        l.addHandler(handler)
        l.propagate = False


class JsonFormatter(logging.Formatter):
    """One JSON line per log record — compatible with Cloud Logging fluentd parser."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        # Capture standard structured fields from the record
        payload = {
            "message": record.getMessage(),
            "severity": record.levelname,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "correlation_id": getattr(record, "correlation_id", None),
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "status_code": getattr(record, "status_code", None),
            "client_host": getattr(record, "client_host", None),
            "user_agent": getattr(record, "user_agent", None),
            "error_type": getattr(record, "error_type", None),
            "error_message": getattr(record, "error_message", None),
            "service": "retailtwin-api",
            "logger": record.name,
            "level": record.levelname,
        }
        # Forward extra fields (event_id, sku, store_id, etc.) into the output
        for k, v in record.__dict__.items():
            if k not in payload and not k.startswith("_"):
                payload[k] = v
        return json.dumps({k: v for k, v in payload.items() if v is not None}, separators=(",", ":"))


# Apply JSON logging at module import time (safe to call multiple times).
_configure_json_logging()

# Stable dict for documentation and potential future dictConfig use.
# Components that need the handler (e.g., tests) can call _get_json_handler().
LOGGING_CONFIG: dict = {"version": 1}  # Minimal placeholder


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Injects X-Correlation-ID into every request and emits a structured start/end log."""

    HEADER = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get(self.HEADER) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        # Emit structured request-start log (includes Cloud Run metadata fields)
        logger.info(
            f"request.start correlation_id={correlation_id}",
            extra={
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request.error",
                extra={
                    "correlation_id": correlation_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise

        # Emit structured request-end log
        logger.info(
            f"request.end correlation_id={correlation_id}",
            extra={
                "correlation_id": correlation_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )

        response.headers[self.HEADER] = correlation_id
        return response
