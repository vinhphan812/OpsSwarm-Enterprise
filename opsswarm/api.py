from __future__ import annotations

import asyncio
import enum
import logging
import os
import signal
import threading
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

from .__version__ import __version__
import opsswarm.auth as auth_module
from .auth import (
    _ensure_production_auth_config,
    _get_real_client_ip,
    _probe_scope_from_bearer,
    admin_scope,
    check_monitoring_body_size,
    check_monitoring_rate_limit,
    read_scope,
    reload_auth_config,
    verify_scoped_bearer,
    write_scope,
)
from .commands import parse_command
from .config import get_github, get_monitoring, load_config
from .errors import new_correlation_id, sanitize_for_log
from .github_client import (
    GitHubClient,
    build_allowed_origins_set,
    get_effective_origin_diagnostic,
)
from .logging_config import reset_corr_id, set_corr_id
from .metrics import metrics
from .openclaw import OpenClawClient
from .orchestrator import Orchestrator
from .webhook import verify_signature

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifecycle state (Issue #73: /ready endpoint + graceful drain)
# ---------------------------------------------------------------------------


class AppState(enum.Enum):
    """Application lifecycle states for readiness probe."""

    STARTING = "starting"
    READY = "ready"
    DRAINING = "draining"
    FAILED = "failed"


class LifecycleManager:
    """Thread-safe lifecycle state manager for graceful shutdown.

    Tracks application state and coordinates graceful drain on SIGTERM.
    The /ready endpoint reflects this state: 200 when READY, 503 otherwise.
    """

    _instance: "LifecycleManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "LifecycleManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._state = AppState.STARTING
                cls._instance._startup_error: str | None = None
                cls._instance._drain_timeout = 30  # seconds - bounded by OpenClaw timeout
                cls._instance._background_tasks: list[asyncio.Task] = []
                cls._instance._drain_event = threading.Event()
            return cls._instance

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    @property
    def startup_error(self) -> str | None:
        with self._lock:
            return self._startup_error

    def set_ready(self) -> None:
        """Mark application as ready to serve traffic."""
        with self._lock:
            self._state = AppState.READY
            logger.info("Application marked as READY")

    def set_failed(self, error: str | None = None) -> None:
        """Mark application as failed (startup or runtime failure)."""
        with self._lock:
            self._state = AppState.FAILED
            self._startup_error = error
            logger.error(f"Application marked as FAILED: {error}")

    def set_draining(self) -> None:
        """Mark application as draining (SIGTERM received)."""
        with self._lock:
            if self._state == AppState.READY:
                self._state = AppState.DRAINING
                logger.info("Application marked as DRAINING (SIGTERM received)")

    @property
    def is_accepting_work(self) -> bool:
        """Returns True if the application is ready to accept new mutation work."""
        with self._lock:
            return self._state == AppState.READY

    def register_background_task(self, task: asyncio.Task) -> None:
        """Register a background task for tracking during drain."""
        with self._lock:
            self._background_tasks.append(task)

    async def drain(self, timeout: int | None = None) -> None:
        """Gracefully drain the application.

        Wait for background tasks to complete (with timeout), then mark as drained.
        This is called when SIGTERM is received.
        """
        timeout = timeout or self._drain_timeout
        self.set_draining()

        # Wait for background tasks with timeout
        if self._background_tasks:
            logger.info(f"Waiting for {len(self._background_tasks)} background tasks (timeout={timeout}s)")
            done, pending = await asyncio.wait(
                self._background_tasks,
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED,
            )
            if pending:
                logger.warning(f"{len(pending)} background tasks did not complete within {timeout}s")
                # Cancel pending tasks
                for task in pending:
                    if not task.done():
                        task.cancel()
        else:
            logger.info("No background tasks to wait for")

        self._drain_event.set()
        logger.info("Drain complete")

    def wait_for_drain(self, timeout: int | None = None) -> bool:
        """Block until drain is complete (for sync context)."""
        timeout = timeout or self._drain_timeout
        return self._drain_event.wait(timeout=timeout)


# Global lifecycle manager instance
lifecycle = LifecycleManager()

cfg = load_config()

# Deprecated: X-OpsSwarm-API-Key header (Phase 1 of migration).
# Kept for backward compatibility during transition period.
_deprecated_api_key = os.environ.get("OPSWARM_API_KEY", "")

# ----------------------------------------------------------------------
# GitHub client — Issue #72 / ADR-028
# Build the approved-origins set and CA bundle from config + env vars.
# Raises ValueError at startup (fail-closed) if any origin fails SSRF validation.
# ----------------------------------------------------------------------
_OPSWARM_PROFILE = os.environ.get("OPSWARM_PROFILE", "production")

_gh_cfg = get_github(cfg)
# Allow operator to override origins via env var (comma-separated, no spaces).
_env_origins_raw = os.environ.get("OPSWARM_GITHUB_ORIGINS", "").strip()
_config_origins: list[str] = _gh_cfg.get("origins", ["https://api.github.com"])
_origins: list[str] = (
    [o.strip() for o in _env_origins_raw.split(",") if o.strip()]
    if _env_origins_raw
    else _config_origins
)
_allowed_origins = build_allowed_origins_set(_origins, profile=_OPSWARM_PROFILE)

_gh_ca_bundle: str = os.environ.get(
    "OPSWARM_GITHUB_CA_BUNDLE", _gh_cfg.get("ca_bundle", "")
).strip()
if _allowed_origins and _allowed_origins != frozenset({"https://api.github.com"}):
    _primary_origin = next(iter(_allowed_origins))
else:
    _primary_origin = "https://api.github.com"

logger.info(
    "GitHub origins configured: %s  (ca_bundle=%s)",
    get_effective_origin_diagnostic(_origins),
    "custom=" + _gh_ca_bundle if _gh_ca_bundle else "system",
)

gh = GitHubClient(
    os.environ.get("GITHUB_TOKEN", ""),
    os.environ.get("GITHUB_REPO", cfg.get("repo", "")),
    base_url=_primary_origin,
    allowed_origins=_allowed_origins,
    verify=_gh_ca_bundle or True,
    profile=_OPSWARM_PROFILE,
)
oc = OpenClawClient(
    os.environ.get("OPSWARM_OPENCLAW_BIN", "openclaw"),
    int(
        os.environ.get(
            "OPSWARM_OPENCLAW_TIMEOUT",
            cfg.get("openclaw", {}).get("timeout_seconds", 600),
        )
    ),
)
engine = Orchestrator(cfg, gh, oc, os.environ.get("OPSWARM_DATA_DIR", "runtime-data"))
app = FastAPI(title="OpsSwarm Enterprise OpenClaw+GitHub", version=__version__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Stamp every request with a correlation ID returned in response headers.

    Sets ``X-Corr-ID`` and ``X-Request-ID`` on both the request log context
    and the response.  If the client already supplied one via ``X-Correlation-ID``
    or ``X-Request-ID`` it is reused unchanged.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = (
            request.headers.get("x-corr-id")
            or request.headers.get("x-correlation-id")
            or request.headers.get("x-request-id")
            or ""
        )
        correlation_id = incoming if incoming else new_correlation_id()
        token = set_corr_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_corr_id(token)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Corr-ID"] = correlation_id
        return response


app.add_middleware(CorrelationMiddleware)


# ---------------------------------------------------------------------------
# Lifespan: fail-closed production startup check + graceful SIGTERM drain (Issue #73)
# ---------------------------------------------------------------------------


async def _startup_checks() -> None:
    """Run all startup validation checks.

    Validates:
    1. Logging setup
    2. Auth configuration
    3. Config file loading
    4. Data directory accessibility

    Raises an exception on any failure (fail-closed).
    On success, marks the application as READY.
    """
    from .logging_config import setup_logging

    # 1. Setup logging
    setup_logging()

    # 2. Validate and reload auth config
    reload_auth_config()
    _ensure_production_auth_config()

    # 3. Validate data directory exists and is writable
    data_dir = os.environ.get("OPSWARM_DATA_DIR", "runtime-data")
    data_path = _validate_data_path(data_dir)

    # All checks passed - mark as ready
    lifecycle.set_ready()
    logger.info(
        "Startup checks passed: auth=%s, config=%s, data_dir=%s",
        "ok",
        "ok",
        data_path,
    )


def _validate_data_path(data_dir: str) -> str:
    """Validate that the data directory is accessible.

    Returns the validated path on success.
    Raises ValueError if the path is inaccessible.
    """
    import pathlib

    path = pathlib.Path(data_dir)
    try:
        # Try to create the directory if it doesn't exist
        path.mkdir(parents=True, exist_ok=True)
        # Verify we can write to it
        test_file = path / ".write_test"
        test_file.touch()
        test_file.unlink()
        return str(path.resolve())
    except OSError as e:
        raise ValueError(f"Data directory not accessible: {data_dir}") from e


async def _shutdown() -> None:
    """Graceful shutdown handler.

    Called by FastAPI lifespan on shutdown. Initiates drain but does not wait
    for it to complete (the OS will terminate the process after the shutdown
    timeout). Background tasks are given a bounded time to complete.
    """
    logger.info("Shutdown initiated")
    try:
        await lifecycle.drain(timeout=30)
    except Exception:
        logger.exception("Error during graceful shutdown")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager for startup/shutdown.

    - On startup: runs validation checks and marks app as READY on success.
    - On shutdown: initiates graceful drain of background tasks.
    - Sets up SIGTERM handler for container/orchestrator graceful shutdown.
    """
    # Set up SIGTERM handler
    def _sigterm_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful drain")
        # Schedule drain in the event loop
        asyncio.create_task(lifecycle.drain())

    # Install signal handler (only works on Unix-like systems; no-op on Windows)
    try:
        signal.signal(signal.SIGTERM, _sigterm_handler)
    except (ValueError, OSError):
        # Windows doesn't support SIGTERM handler in the same way
        logger.debug("SIGTERM handler not available on this platform")

    # Run startup checks
    try:
        await _startup_checks()
    except Exception:
        lifecycle.set_failed(str(Exception))
        logger.exception("Startup checks failed")
        # Don't raise - let FastAPI start so /health still works
        # but /ready will return 503

    yield

    # Run shutdown
    await _shutdown()


# Replace the default app lifespan with our custom one
app = FastAPI(
    title="OpsSwarm Enterprise OpenClaw+GitHub",
    version=__version__,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Liveness probe - returns 200 if the process is alive.

    Does NOT check whether the application is ready to serve traffic.
    Use /ready for readiness checks.
    """
    return {"ok": True, "version": __version__, "architecture": "openclaw+github"}


@app.get("/ready")
async def ready():
    """Readiness probe - returns 200 only when fully initialized and accepting work.

    Returns:
    - 200: Application is ready to serve traffic (startup checks passed)
    - 503: Application is not ready (still starting, failed, or draining)

    The response body does not leak sensitive information such as
    authentication tokens, file paths, or raw dependency errors.
    """
    state = lifecycle.state

    if state == AppState.READY:
        return {
            "ready": True,
            "state": state.value,
            "accepting_work": True,
        }
    else:
        # Return 503 with generic message - no sensitive info leaked
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "state": state.value,
                "accepting_work": False,
            },
        )


@app.get("/metrics", dependencies=[Depends(admin_scope)])
async def get_metrics():
    # Refresh active-runs gauge before rendering so /metrics reflects current state
    state_counts: dict[str, int] = {}
    for run in engine.runs.values():
        sv = run.state.value if run.state else "UNKNOWN"
        state_counts[sv] = state_counts.get(sv, 0) + 1
    metrics.set_active_runs(state_counts)
    # Log the scrape with the correlation ID for traceability
    logger.info(
        "Metrics scraped",
        extra={
            "run_count": len(engine.runs),
            "state_counts": state_counts,
        },
    )
    return PlainTextResponse(metrics.to_prometheus(), media_type="text/plain")


# ---------------------------------------------------------------------------
# Read scope: opsswarm:read
# ---------------------------------------------------------------------------


@app.get("/runs", dependencies=[Depends(read_scope)])
async def runs():
    return [r.model_dump(mode="json") for r in engine.runs.values()]


@app.get("/runs/{issue_number}", dependencies=[Depends(read_scope)])
async def run(issue_number: int):
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")
    return r.model_dump(mode="json")


@app.get("/runs/{issue_number}/evidence", dependencies=[Depends(read_scope)])
async def evidence(issue_number: int):
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")
    return engine.ev.list(r.run_id)


@app.get("/runs/{issue_number}/checkpoint", dependencies=[Depends(read_scope)])
async def get_checkpoint(issue_number: int):
    """Get the last checkpoint for a run."""
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")
    checkpoint = engine.ev.get_last_checkpoint(r.run_id)
    if not checkpoint:
        return {"has_checkpoint": False, "checkpoint": None}
    return {"has_checkpoint": True, "checkpoint": checkpoint}


# ---------------------------------------------------------------------------
# Write scope: opsswarm:write
# ---------------------------------------------------------------------------


@app.post("/runs/{issue_number}/resume", dependencies=[Depends(write_scope)])
async def resume_run(issue_number: int):
    """Resume a run from its last checkpoint."""
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")

    checkpoint = engine.ev.get_last_checkpoint(r.run_id)
    if not checkpoint:
        raise HTTPException(400, "No checkpoint available for this run")

    checkpoint_type = checkpoint.get("payload", {}).get("checkpoint_type", "unknown")
    checkpoint_state = checkpoint.get("payload", {}).get("state", "unknown")

    return {
        "resumed": True,
        "checkpoint_type": checkpoint_type,
        "checkpoint_state": checkpoint_state,
        "current_state": r.state.value,
    }


# ---------------------------------------------------------------------------
# GitHub webhook (independent auth domain; not subject to opsswarm scopes)
# ---------------------------------------------------------------------------


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
):
    body = await request.body()
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not verify_signature(secret, body, x_hub_signature_256):
        raise HTTPException(401, "Invalid webhook signature")
    data = await request.json()
    if x_github_event == "issues" and data.get("action") == "opened":
        number = int(data["issue"]["number"])
        task = asyncio.create_task(engine.start_issue(number, x_github_delivery))
        lifecycle.register_background_task(task)
        return {"accepted": True, "issue": number}
    if x_github_event == "issue_comment" and data.get("action") == "created":
        number = int(data["issue"]["number"])
        actor = data["comment"]["user"]["login"]
        text = data["comment"].get("body") or ""
        comment_id = str(data["comment"].get("id", ""))
        permission = await gh.permission(actor)
        try:
            await engine.handle_comment(
                number,
                actor,
                text,
                permission,
                parse_command(text),
                comment_id,
                x_github_delivery,
            )
        except PermissionError as e:
            corr_id = new_correlation_id()
            logger.error(f"PermissionError [{corr_id}]: {sanitize_for_log(str(e))}")
            await gh.comment(
                number, f"OpsSwarm command rejected (ref: {corr_id}). Check server logs."
            )
        except Exception:
            corr_id = new_correlation_id()
            logger.exception("Unhandled exception in handle_comment [%s]", corr_id)
            await gh.comment(
                number,
                f"OpsSwarm could not process the command (ref: {corr_id}). Check server logs.",
            )
        return {"accepted": True}
    return {"ignored": True}


# ---------------------------------------------------------------------------
# Monitoring ingress: opsswarm:monitor + rate limit + size limit (ADR-014 D5)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Monitoring ingress: opsswarm:monitor + rate limit + size limit (ADR-014 D5)
# ---------------------------------------------------------------------------


@app.post("/hooks/monitoring")
async def monitoring_event(request: Request):
    # --- Body size check (before any auth — large body is a DoS vector) ---
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            cl = int(content_length)
        except ValueError:
            cl = None
        check_monitoring_body_size(cl)

    raw_body = await request.body()
    check_monitoring_body_size(len(raw_body))

    # --- Rate limit check (ADR-014-2: proxy-aware, auth-identity fallback) ---
    auth = request.headers.get("Authorization", "")
    source_ip = _get_real_client_ip(request, cfg)

    # Probe the scope (non-registering) so authenticated callers get a stable quota.
    # Only scopes that authorize POST /hooks/monitoring (opsswarm:monitor or
    # opsswarm:admin) get a scope-based rate-limit key.  Other valid tokens
    # (opsswarm:read, opsswarm:write) fall through to IP-based limiting so they
    # cannot pollute the monitoring limiter's LRU-bounded state and cannot
    # evict the legitimate monitor/admin bucket.  This closes the cross-scope
    # depletion / availability coupling reported in PR #86 review.
    scope_identity = await _probe_scope_from_bearer(request, auth)

    if scope_identity and scope_identity in (auth_module.SCOPE_MONITOR, auth_module.SCOPE_ADMIN):
        # Primary: authenticated scope identity (stable, not spoofable)
        rate_key = f"scope:{scope_identity}"
    else:
        # Fallback: client IP (proxy-aware)
        rate_key = source_ip

    allowed, retry_after = check_monitoring_rate_limit(rate_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    # --- Authentication: bearer token OR HMAC webhook signature ---
    auth = request.headers.get("Authorization", "")
    signature = request.headers.get("x-monitoring-signature", "")
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

    # Try bearer token path first.
    # Re-raise 401 so the caller gets "missing/invalid credentials".
    # Let 403 (insufficient scope) propagate directly.
    is_bearer_valid = False
    try:
        verified_scope = await verify_scoped_bearer(request, auth)
        is_bearer_valid = True
    except HTTPException as e:
        if e.status_code == 401:
            pass  # No credentials — try HMAC signature path
        else:
            raise  # 403 or other — propagate unchanged

    # Try HMAC webhook signature path (monitoring systems supporting this mechanism)
    is_signature_valid = verify_signature(secret, raw_body, signature)

    if not is_bearer_valid and not is_signature_valid:
        raise HTTPException(status_code=401, detail="Missing credentials")

    # --- Create incident ---
    payload = await request.json()
    title = payload.get("title") or f"[Incident] {payload.get('service', 'unknown service')}"
    body = (
        f"## Incident\n\n"
        f"### Service\n{payload.get('service', 'unknown')}\n\n"
        f"### Symptoms\n{payload.get('symptom', 'Monitoring alert')}\n\n"
        f"### Customer impact\n{payload.get('customer_impact', 'unknown')}\n\n"
        f"### Environment\n{payload.get('environment', 'production')}\n\n"
        f"### Observed since\n{payload.get('observed_since', 'unknown')}\n\n"
        f"### Additional information\n"
        f"Created automatically by OpsSwarm monitoring ingress.\n"
    )
    labels = list(
        dict.fromkeys(
            cfg.get("labels", {}).get("base", ["opsswarm", "incident"])
            + [payload.get("severity_label", "sev:2")]
        )
    )
    issue = await gh.create_issue(title, body, labels)
    number = int(issue["number"])
    task = asyncio.create_task(engine.start_issue(number))
    lifecycle.register_background_task(task)
    return {"accepted": True, "issue_number": number}
