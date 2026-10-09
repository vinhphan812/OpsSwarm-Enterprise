from __future__ import annotations

import asyncio
import logging
import os

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
from .runtime import check_draining, readiness
from .webhook import verify_signature

logger = logging.getLogger(__name__)

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
# Lifespan: fail-closed production startup check (ADR-014 D4)
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def _startup_auth_check():
    from .logging_config import setup_logging

    setup_logging()
    reload_auth_config()
    _ensure_production_auth_config()
    await readiness.startup_complete()


@app.on_event("shutdown")
async def _shutdown_drain():
    await readiness.initiate_drain()


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"ok": True, "version": __version__, "architecture": "openclaw+github"}


@app.get("/ready")
async def ready():
    """Readiness endpoint. 200 if OK, else 503."""
    if not readiness.ready:
        raise HTTPException(
            status_code=503,
            detail="Startup incomplete or service is draining",
        )
    return {"ok": True}


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
@check_draining
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
@check_draining
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
        asyncio.create_task(engine.start_issue(number, x_github_delivery))
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
@check_draining
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
    asyncio.create_task(engine.start_issue(number))
    return {"accepted": True, "issue_number": number}
