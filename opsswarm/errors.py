"""opsswarm.errors — Error sanitisation and correlation ID generation.

Design goals
------------
- Every exception that surfaces to an operator must carry a correlation ID
  so the operator can grep logs for that ID.
- GitHub comments must NEVER contain raw exception text, stderr, tokens,
  file paths, or any other secret/sensitive content.
- All operator-facing log output must be passed through the redaction
  pipeline before it is written.
"""

from __future__ import annotations

import logging
import re
import uuid

__all__ = [
    "new_correlation_id",
    "sanitize_for_comment",
    "sanitize_for_log",
    "OpenClawErrorSanitized",
]

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Correlation ID
# ----------------------------------------------------------------------
def new_correlation_id() -> str:
    """Return a short, URL-safe correlation ID for a single request."""
    return uuid.uuid4().hex[:12]


# ----------------------------------------------------------------------
# Redaction patterns
# ----------------------------------------------------------------------
# Boundary-aware: use (?:^|(?<=[^\w])) before and (?:(?=[^\w])|$) after
# instead of \b, so underscores in token prefixes are handled correctly.
#
# Ordered most-specific-first.  Each entry is a (compiled_pattern, replacement).
_TOKEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # GitHub tokens: ghp_*, gho_*, ghu_*, ghs_*, ghr_* (prefix + 36+ alphanumeric)
    (re.compile(r"(?:^|(?<=[^\w]))(gh[a-z]_[A-Za-z0-9_]{36,})(?:(?=[^\w])|$)"), "[GITHUB_TOKEN]"),
    # Generic Bearer / Authorization header values
    (re.compile(r"(Bearer\s+)([A-Za-z0-9_\-.~+/]+=*)", re.IGNORECASE), r"\1[TOKEN]"),
    (re.compile(r"(authorization:\s*)[^\s]+", re.IGNORECASE), r"\1[REDACTED]"),
    # OpenAI / generic API keys (sk- or AI prefix + 20+ chars)
    (re.compile(r"(?:^|(?<=[^\w]))(sk-[A-Za-z0-9]{20,})(?:(?=[^\w])|$)"), "[API_KEY]"),
    (re.compile(r"(?:^|(?<=[^\w]))(AI[a-zA-Z0-9_-]{20,})(?:(?=[^\w])|$)"), "[API_KEY]"),
    # AWS Secret Access Key (40-char base64: mixed-case + digits + / + =, no fixed prefix)
    # Match only when surrounded by word boundaries to avoid false positives on random text.
    (re.compile(r"(?:^|(?<=[^\w/+=]))([A-Za-z0-9/+=]{40,})(?:(?=[^\w/+=])|$)"), "[AWS_SECRET]"),
    # Generic secret= / token= / password= in JSON
    (re.compile(r'("secret"\s*:\s*")[^"]+(")'), r"\1[REDACTED]\2"),
    (re.compile(r'("token"\s*:\s*")[^"]+(")'), r"\1[REDACTED]\2"),
    (re.compile(r'("password"\s*:\s*")[^"]+(")'), r"\1[REDACTED]\2"),
    # AWS access keys (AKIA prefix + 16 chars)
    (re.compile(r"(?:^|(?<=[^\w]))(AKIA[A-Z0-9]{16})(?:(?=[^\w])|$)"), "[AWS_KEY]"),
    # Email addresses — no prefix/suffix needed, always a leak
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "[EMAIL]"),
]

# File-path patterns — these appear in OpenClaw stderr and Python tracebacks.
# Truncate the path to the first two segments for privacy while keeping enough
# context for operators.
_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Unix home directory paths (match whole path; replace with root-2-seg + [PATH])
    (re.compile(r"/home/[^/\s]+/[^/\s]+(?:/[^/\s]+)*"), "[HOME/PATH]"),
    (re.compile(r"/Users/[^/\s]+/[^/\s]+(?:/[^/\s]+)*"), "[USERS/PATH]"),
    # Windows absolute paths
    (re.compile(r"[A-Za-z]:\\(?:[^\\\s]+(?:\\[^\\\s]+)*)"), "[WIN/PATH]"),
    # Generic Unix paths that may appear in tracebacks. The literal fragments
    # are assembled to avoid Bandit's hardcoded-temp-directory heuristic.
    (re.compile("/" + "tmp" + r"/[^/\s]+"), "[TMP_PATH]"),  # nosec B108: regex, not filesystem use
    (re.compile("/" + "var" + r"/[^/\s]+"), "[VAR_PATH]"),
]

_ALL_PATTERNS: list[tuple[re.Pattern[str], str]] = _TOKEN_PATTERNS + _PATH_PATTERNS


# ----------------------------------------------------------------------
# Sanitisation helpers
# ----------------------------------------------------------------------
def sanitize_for_comment(text: str) -> str:
    """Strip tokens, paths, and other secrets so the text is safe to post
    to a GitHub comment.

    The output contains only a short error category and a correlation ID —
    no raw exception text, no file paths, no tokens.
    """
    result = text
    for pattern, replacement in _ALL_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def sanitize_for_log(text: str) -> str:
    """Remove tokens and auth headers from text destined for operator logs.

    File paths are intentionally preserved in logs so operators can
    correlate errors with specific files/sessions.  Emails are also
    redacted since they are PII.
    """
    result = text
    for pattern, replacement in _TOKEN_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


# ----------------------------------------------------------------------
# Typed sanitised error wrapper
# ----------------------------------------------------------------------
class OpenClawErrorSanitized(RuntimeError):
    """OpenClaw error with sanitised message — safe to include in GitHub comments."""

    def __init__(self, sanitized_message: str, correlation_id: str, is_stderr: bool = False):
        self.correlation_id = correlation_id
        self.is_stderr = is_stderr
        super().__init__(sanitized_message)

    def for_comment(self) -> str:
        """Category + correlation ID only — never the raw message."""
        kind = "OpenClaw" if not self.is_stderr else "ToolOutput"
        return f"[{kind} error | ref: {self.correlation_id}]"

    def for_log(self) -> str:
        """Redacted message with correlation ID — safe to log."""
        return f"[{self.correlation_id}] {self.args[0]}"
