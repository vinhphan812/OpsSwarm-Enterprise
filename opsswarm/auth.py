"""ADR-014 Runtime API Authentication.

HMAC-SHA256 scoped bearer tokens + pre-shared static keys.
Scope hierarchy: admin > write > read; monitor is strictly separate.

Environment variables
---------------------
OPSWARM_RUNTIME_SECRET   Master secret for HMAC-SHA256 token derivation.
OPSWARM_API_KEY_READ     Static bearer token granting opsswarm:read.
OPSWARM_API_KEY_WRITE    Static bearer token granting opsswarm:write.
OPSWARM_API_KEY_MONITOR  Static bearer token granting opsswarm:monitor.
OPSWARM_API_KEY_ADMIN    Static bearer token granting opsswarm:admin.
APP_ENV                   Set to "production" to enforce startup-time config check.

Token format
------------
Authorization: Bearer <scope>=<hmac_hex>

Scope:   opsswarm:read | opsswarm:write | opsswarm:monitor | opsswarm:admin
hmac_hex = HMAC-SHA256(OPSWARM_RUNTIME_SECRET, "<method>:<path>:<unix_ts>")
Token is valid for ±60 s around server clock (anti-replay).

Static key path: any OPSWARM_API_KEY_<SCOPE> value used directly as the bearer
value grants that scope. HMAC and static paths are checked in sequence.

Production fail-closed (ADR-014 D4):
  APP_ENV=production + no OPSWARM_RUNTIME_SECRET + no OPSWARM_API_KEY_* →
  RuntimeError at startup.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
from typing import Final

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_ENV_KEY = "APP_ENV"
PRODUCTION_ENV = "production"
DEVELOPMENT_ENV = "development"

RUNTIME_SECRET_KEY = "OPSWARM_RUNTIME_SECRET"  # nosec: B105  # env-var key, not a secret value
API_KEY_PREFIX = "OPSWARM_API_KEY_"  # nosec: B105  # env-var key prefix, not a value

SCOPE_READ = "opsswarm:read"
SCOPE_WRITE = "opsswarm:write"
SCOPE_MONITOR = "opsswarm:monitor"
SCOPE_ADMIN = "opsswarm:admin"

# Ordered from most- to least-privileged for the hierarchy check.
ALL_SCOPES: Final = [SCOPE_ADMIN, SCOPE_WRITE, SCOPE_MONITOR, SCOPE_READ]

# Mapping: scope → set of allowed endpoint method+path prefixes.
# Path prefixes use the actual route segments; variable parts match by prefix.
# e.g. "POST /runs" covers POST /runs/1/resume, POST /runs/42/evidence, etc.
SCOPE_ENDPOINTS: Final = {
    SCOPE_READ: {"GET /runs", "GET /metrics"},
    SCOPE_WRITE: {"POST /runs", "GET /runs", "GET /metrics"},
    SCOPE_MONITOR: {"POST /hooks/monitoring"},
    SCOPE_ADMIN: {"GET /runs", "GET /metrics", "POST /runs", "POST /hooks/monitoring"},
}

# Token lifetime and clock-skew tolerance
TOKEN_TTL_SECONDS = 300  # 5 minutes
SKEW_TOLERANCE_SECS = 60  # ±60 s

# Monitoring ingress limits (ADR-014 D5)
MONITORING_MAX_BYTES = 64 * 1024  # 64 KiB
MONITORING_RATE_LIMIT = 20  # req/min per source

# Request context keys
CTX_SCOPE_KEY = "opsswarm_scope"  # Starlette request.state key

# ---------------------------------------------------------------------------
# Rate limiting (in-process, per-process)
# ---------------------------------------------------------------------------


class _SimpleRateLimiter:
    """Per-source-IP or per-token rate limiter.

    Uses a sliding window counter.  Suitable for single-instance deployments.
    For multi-instance, replace with Redis-backed implementation.
    """

    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        self._max = max_requests
        self._window = window_seconds
        # {(source_id,): [timestamp, ...]}
        self._hits: dict[tuple, list[float]] = {}

    def is_allowed(self, source_id: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        key = (source_id,)
        timestamps = self._hits.get(key, [])
        # Prune expired entries
        cutoff = now - self._window
        timestamps = [t for t in timestamps if t > cutoff]
        self._hits[key] = timestamps

        if len(timestamps) >= self._max:
            oldest = min(timestamps)
            retry_after = int(oldest + self._window - now) + 1
            return False, max(1, retry_after)

        timestamps.append(now)
        return True, 0


_monitoring_limiter = _SimpleRateLimiter(
    max_requests=MONITORING_RATE_LIMIT,
    window_seconds=60,
)

# ---------------------------------------------------------------------------
# Anti-replay token tracker
# ---------------------------------------------------------------------------


class _AntiReplayStore:
    """Tracks used HMAC tokens within the validity window to detect replay.

    Stores (scope, method, path, hmac_hex) tuples keyed by timestamp bucket.
    Tokens outside the window are evicted automatically.
    """

    def __init__(self) -> None:
        # {hmac_hex: expiry_unix}
        self._used: dict[str, float] = {}
        self._window = TOKEN_TTL_SECONDS + SKEW_TOLERANCE_SECS

    def is_replay(self, token: str) -> bool:
        """Return True if this exact token has already been used."""
        # We store the HMAC portion of the token
        if "=" not in token:
            return False
        hmac_hex = token.split("=", 1)[1]
        now = time.time()
        # Evict expired entries
        expired = [k for k, v in self._used.items() if v < now - self._window]
        for k in expired:
            del self._used[k]

        if hmac_hex in self._used:
            return True
        self._used[hmac_hex] = now
        return False

    def reset(self) -> None:
        """Clear all replay state. Used by tests."""
        self._used.clear()


_anti_replay = _AntiReplayStore()

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_opsswarm_runtime_secret: str | None = None
_preshared_keys: dict[str, str] = {}  # scope → static bearer value

# Compiled regex for bearer token: "scope=hex..."
_BEARER_RE = re.compile(r"^([a-z0-9:_-]+)=([0-9a-f]{64})$")


def reload_auth_config() -> None:
    """Reload secret material from the environment.

    Call this after mutating the process environment (e.g. in tests or
    when the operator rotates credentials via a signal).
    """
    global _opsswarm_runtime_secret, _preshared_keys
    _opsswarm_runtime_secret = os.environ.get(RUNTIME_SECRET_KEY) or None
    _preshared_keys = {
        SCOPE_READ: os.environ.get(f"{API_KEY_PREFIX}READ", ""),
        SCOPE_WRITE: os.environ.get(f"{API_KEY_PREFIX}WRITE", ""),
        SCOPE_MONITOR: os.environ.get(f"{API_KEY_PREFIX}MONITOR", ""),
        SCOPE_ADMIN: os.environ.get(f"{API_KEY_PREFIX}ADMIN", ""),
    }
    # Normalise: drop empty-string entries
    _preshared_keys = {k: v for k, v in _preshared_keys.items() if v}


def _has_any_auth_config() -> bool:
    """True if at least one auth mechanism is configured."""
    reload_auth_config()
    return bool(_opsswarm_runtime_secret) or bool(_preshared_keys)


def _ensure_production_auth_config() -> None:
    """Raise RuntimeError if production env lacks auth config.

    Called at FastAPI lifespan startup.
    """
    env = os.environ.get(APP_ENV_KEY, DEVELOPMENT_ENV)
    if env.lower() != PRODUCTION_ENV:
        return  # Only enforced in production
    if not _has_any_auth_config():
        raise RuntimeError(
            "OPSWARM_RUNTIME_SECRET or OPSWARM_API_KEY_<SCOPE> must be set in "
            "production. Set APP_ENV=development for local runs without auth."
        )


# Load on module import
reload_auth_config()

# ---------------------------------------------------------------------------
# Token generation helpers (for operators / tests)
# ---------------------------------------------------------------------------


def generate_bearer_token(
    scope: str,
    secret: str,
    method: str,
    path: str,
    timestamp: int | None = None,
) -> str:
    """Generate a scoped HMAC bearer token for the given request parameters.

    Operators use this to mint tokens for their CI systems or monitoring tools.
    """
    ts = timestamp if timestamp is not None else int(time.time())
    payload = f"{method.upper()}:{path}:{ts}"
    mac = hmac.new(
        secret.encode("ascii"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{scope}={mac}"


def verify_bearer_hmac(
    token_scope: str,
    token_hmac_hex: str,
    secret: str,
    method: str,
    path: str,
    timestamp: int,
) -> bool:
    """Constant-time HMAC comparison for a bearer token."""
    if timestamp < int(time.time()) - SKEW_TOLERANCE_SECS:
        return False
    if timestamp > int(time.time()) + SKEW_TOLERANCE_SECS:
        return False
    payload = f"{method.upper()}:{path}:{timestamp}"
    expected_mac = hmac.new(
        secret.encode("ascii"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    # Constant-time comparison
    return hmac.compare_digest(expected_mac, token_hmac_hex)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _scope_covers_endpoint(scope: str, method: str, path: str) -> bool:
    """Return True if `scope` authorises `method` + `path`.

    Uses prefix matching: e.g. "POST /runs" covers "POST /runs/1/resume".
    """
    key = f"{method.upper()} {path}"

    # Build the effective scopes (admin implies all others)
    hierarchy = {
        SCOPE_ADMIN: (SCOPE_ADMIN, SCOPE_WRITE, SCOPE_MONITOR, SCOPE_READ),
        SCOPE_WRITE: (SCOPE_WRITE, SCOPE_READ),
        SCOPE_MONITOR: (SCOPE_MONITOR,),
        SCOPE_READ: (SCOPE_READ,),
    }

    for s in hierarchy.get(scope, ()):
        allowed = SCOPE_ENDPOINTS.get(s, set())
        for pattern in allowed:
            if key == pattern or key.startswith(pattern + "/"):
                return True
    return False


def _redact_for_log(value: str, max_len: int = 16) -> str:
    """Redact a bearer token value for safe operator logging."""
    if len(value) <= max_len:
        return "[TOKEN]"
    return value[:max_len] + "[...]"


# ---------------------------------------------------------------------------
# Main bearer validator
# ---------------------------------------------------------------------------


async def verify_scoped_bearer(
    request: Request,
    authorization: str | None,
) -> str:
    """FastAPI dependency: validate a scoped HMAC bearer token.

    Returns the validated scope string on success.
    Raises HTTPException 401 or 403 on failure.

    Validation order:
    1. Missing Authorization header → 401 Missing credentials.
    2. Malformed header → 401 Invalid credentials.
    3. Anti-replay check → 401 Invalid credentials (replay detected).
    4. Pre-shared static key match → return scope.
    5. HMAC-SHA256 derivation + timestamp window → return scope.
    6. Scope does not cover endpoint → 403 Insufficient scope.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing credentials")

    # Parse "Bearer <token>"
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid credentials")

    raw_token = parts[1]

    # --- Static pre-shared key path ---
    # Static key: the bearer value IS the key (no "scope=hex" format required).
    # Try this first so operators can use simple static tokens.
    for scope_key, static_value in _preshared_keys.items():
        if static_value and hmac.compare_digest(static_value, raw_token):
            # Register in anti-replay store (even static tokens shouldn't be replayed)
            _anti_replay.is_replay(raw_token)
            effective_scope = scope_key
            break
    else:
        effective_scope = None

    # --- HMAC-derived bearer path ---
    if effective_scope is None:
        # Check anti-replay (HMAC hex portion only)
        match = _BEARER_RE.match(raw_token)
        if not match:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token_scope = match.group(1)
        token_hmac_hex = match.group(2)

        # Validate scope name
        if token_scope not in set(ALL_SCOPES):
            raise HTTPException(status_code=403, detail="Insufficient scope for this operation")

        # Anti-replay check using the HMAC hex portion
        if _anti_replay.is_replay(raw_token):
            logger.warning("Anti-replay: token reuse detected [REDACTED]")
            raise HTTPException(status_code=401, detail="Invalid credentials")

        if _opsswarm_runtime_secret:
            method = request.method.upper()
            path = request.url.path
            now = int(time.time())
            for ts_offset in range(-SKEW_TOLERANCE_SECS, SKEW_TOLERANCE_SECS + 1):
                ts = now + ts_offset
                if verify_bearer_hmac(
                    token_scope, token_hmac_hex, _opsswarm_runtime_secret, method, path, ts
                ):
                    effective_scope = token_scope
                    break

    if effective_scope is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # --- Scope-authorization check ---
    if not _scope_covers_endpoint(effective_scope, request.method, request.url.path):
        logger.warning(
            f"Scope mismatch: token scope={effective_scope!r} "
            f"method={request.method!r} path={request.url.path!r} [REDACTED]"
        )
        raise HTTPException(status_code=403, detail="Insufficient scope for this operation")

    # Store scope in request state for downstream use
    request.state.opsswarm_scope = effective_scope
    return effective_scope


# ---------------------------------------------------------------------------
# FastAPI dependency helpers
# ---------------------------------------------------------------------------


async def read_scope(request: Request) -> str:
    """Dependency: requires opsswarm:read scope (admin also permitted)."""
    scope = await verify_scoped_bearer(request, request.headers.get("Authorization"))
    if scope not in (SCOPE_READ, SCOPE_ADMIN):
        raise HTTPException(status_code=403, detail="Insufficient scope for this operation")
    return scope


async def write_scope(request: Request) -> str:
    """Dependency: requires opsswarm:write scope (admin also permitted)."""
    scope = await verify_scoped_bearer(request, request.headers.get("Authorization"))
    if scope not in (SCOPE_WRITE, SCOPE_ADMIN):
        raise HTTPException(status_code=403, detail="Insufficient scope for this operation")
    return scope


async def monitor_scope(request: Request) -> str:
    """Dependency: requires opsswarm:monitor scope (admin also permitted)."""
    scope = await verify_scoped_bearer(request, request.headers.get("Authorization"))
    if scope not in (SCOPE_MONITOR, SCOPE_ADMIN):
        raise HTTPException(status_code=403, detail="Insufficient scope for this operation")
    return scope


async def admin_scope(request: Request) -> str:
    """Dependency: requires opsswarm:admin scope."""
    scope = await verify_scoped_bearer(request, request.headers.get("Authorization"))
    if scope != SCOPE_ADMIN:
        raise HTTPException(status_code=403, detail="Insufficient scope for this operation")
    return scope


# ---------------------------------------------------------------------------
# Monitoring ingress helpers
# ---------------------------------------------------------------------------


def check_monitoring_body_size(content_length: int | None) -> None:
    """Raise HTTPException 413 if monitoring body exceeds 64 KiB."""
    if content_length is not None and content_length > MONITORING_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Request body exceeds maximum size of {MONITORING_MAX_BYTES} bytes",
        )


def check_monitoring_rate_limit(source_id: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds) for monitoring endpoint."""
    return _monitoring_limiter.is_allowed(source_id)


# ---------------------------------------------------------------------------
# Tests reset helper
# ---------------------------------------------------------------------------


def reset_replay_store() -> None:
    """Clear the anti-replay store. For use in tests only."""
    _anti_replay.reset()
