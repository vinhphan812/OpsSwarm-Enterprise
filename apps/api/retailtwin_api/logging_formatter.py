"""Cloud Logging-compatible JSON log formatter.

Structured fields are parsed automatically:
  https://cloud.google.com/logging/docs/agent/logging/python/configuration#struct-param

Each output line is one JSON object with:
  - message: the log "message" field (what Log Explorer shows as the log entry)
  - severity: INFO / WARNING / ERROR (maps to Cloud Logging severity)
  - timestamp: ISO-8601 UTC
  - All extra fields as top-level keys.
"""

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Emits one JSON line per log record, compatible with Cloud Logging fluentd parser."""

    def format(self, record: logging.LogRecord) -> str:
        # Cloud Logging parses structured fields from jsonPayload when
        # the log_name ends with .json — but top-level keys work too, and are
        # more portable (work with any log aggregator).
        payload = {
            "message": record.getMessage(),
            "severity": record.levelname,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            # Standard correlation field — Cloud Trace / Log Analytics pick this up
            # automatically when it matches the header name.
            "correlation_id": getattr(record, "correlation_id", None),
            # Request context
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "status_code": getattr(record, "status_code", None),
            "client_host": getattr(record, "client_host", None),
            "user_agent": getattr(record, "user_agent", None),
            # Error context
            "error_type": getattr(record, "error_type", None),
            "error_message": getattr(record, "error_message", None),
            # Application fields
            "service": "retailtwin-api",
            "logger": record.name,
            "level": record.levelname,
        }
        # Drop None values so the JSON stays clean.
        return json.dumps({k: v for k, v in payload.items() if v is not None}, separators=(",", ":"))
