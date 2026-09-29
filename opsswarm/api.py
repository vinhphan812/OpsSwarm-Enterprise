from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, Request, Header, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader

from .commands import parse_command
from .config import load_config
from .github_client import GitHubClient
from .metrics import metrics
from .openclaw import OpenClawClient
from .orchestrator import Orchestrator
from .webhook import verify_signature

logger = logging.getLogger(__name__)

cfg = load_config()

API_KEY_NAME = "X-OpsSwarm-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def generate_correlation_id() -> str:
    """Generate a short correlation ID (first 8 chars of sha256 of timestamp+random)."""
    data = f"{time.time_ns()}{os.urandom(16).hex()}"
    return hashlib.sha256(data.encode()).hexdigest()[:8]


async def verify_api_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != os.environ.get("OPSWARM_API_KEY"):
        raise HTTPException(status_code=403, detail="Could not validate credentials")
    return api_key


def _get_github_token() -> str:
    """Get GitHub token from environment, preferring explicit GITHUB_TOKEN over GH_TOKEN."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""


_gh_token = _get_github_token()

# Singleton placeholder — replaced lazily by _gh_client().
_gh: GitHubClient | None = None


class _LazyGitHubProxy:
    """Proxy that creates the real GitHubClient on first method call.

    Allows opsswarm.api to be imported without a GITHUB_TOKEN, deferring the
    fail-closed check to request time (503 instead of 500).
    """

    __slots__ = ()

    def _resolve(self) -> GitHubClient:
        global _gh
        if _gh is None:
            if not _gh_token:
                raise HTTPException(
                    status_code=503,
                    detail="GitHub token is not configured. Set GITHUB_TOKEN or GH_TOKEN.",
                )
            _gh = GitHubClient(_gh_token, os.environ.get("GITHUB_REPO", cfg.get("repo", "")))
        return _gh

    def __getattr__(self, name: str):
        return getattr(self._resolve(), name)

    async def __call__(self, *args, **kwargs):
        # Allow `await gh(...)` to resolve lazily (matches old sync usage pattern).
        return await self._resolve()


gh: Any = _LazyGitHubProxy()
oc = OpenClawClient(
    os.environ.get("OPSWARM_OPENCLAW_BIN", "openclaw"),
    int(
        os.environ.get(
            "OPSWARM_OPENCLAW_TIMEOUT", cfg.get("openclaw", {}).get("timeout_seconds", 600)
        )
    ),
)
engine = Orchestrator(cfg, gh, oc, os.environ.get("OPSWARM_DATA_DIR", "runtime-data"))
app = FastAPI(title="OpsSwarm Enterprise OpenClaw+GitHub", version="2.1.0")


@app.get("/health")
async def health():
    return {"ok": True, "version": "2.1.0", "architecture": "openclaw+github"}


@app.get("/metrics")
async def get_metrics():
    from collections import Counter
    from starlette.responses import PlainTextResponse

    # Populate active-runs gauge from current orchestrator state
    state_counts: Counter[str] = Counter()
    for run in engine.runs.values():
        state_counts[run.state.value] += 1
    metrics.set_active_runs(dict(state_counts))

    # Budget utilisation — tasks: ratio of active tasks vs. max_tasks_per_run (50)
    max_tasks = 50
    active_tasks = sum(len(r.tasks) for r in engine.runs.values())
    metrics.set_budget_utilization("tasks", active_tasks / max_tasks)

    return PlainTextResponse(metrics.to_prometheus(), media_type="text/plain")


@app.get("/runs", dependencies=[Depends(verify_api_key)])
async def runs():
    return [r.model_dump(mode="json") for r in engine.runs.values()]


@app.get("/runs/{issue_number}", dependencies=[Depends(verify_api_key)])
async def run(issue_number: int):
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")
    return r.model_dump(mode="json")


@app.get("/runs/{issue_number}/evidence", dependencies=[Depends(verify_api_key)])
async def evidence(issue_number: int):
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")
    return engine.ev.list(r.run_id)


@app.get("/runs/{issue_number}/checkpoint", dependencies=[Depends(verify_api_key)])
async def get_checkpoint(issue_number: int):
    """Get the last checkpoint for a run."""
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")
    checkpoint = engine.ev.get_last_checkpoint(r.run_id)
    if not checkpoint:
        return {"has_checkpoint": False, "checkpoint": None}
    return {"has_checkpoint": True, "checkpoint": checkpoint}


@app.post("/runs/{issue_number}/resume", dependencies=[Depends(verify_api_key)])
async def resume_run(issue_number: int):
    """Resume a run from its last checkpoint."""
    r = engine.runs.get(issue_number)
    if not r:
        raise HTTPException(404, "No run for issue")

    # Check for valid checkpoint
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
        asyncio.create_task(engine.start_issue(number, x_github_delivery))
        return {"accepted": True, "issue": number}
    if x_github_event == "issue_comment" and data.get("action") == "created":
        number = int(data["issue"]["number"])
        actor = data["comment"]["user"]["login"]
        text = data["comment"].get("body") or ""
        # Extract comment ID for idempotency
        comment_id = str(data["comment"].get("id", ""))
        permission = await gh.permission(actor)
        cid = generate_correlation_id()
        try:
            await engine.handle_comment(
                number, actor, text, permission, parse_command(text), comment_id, x_github_delivery
            )
        except PermissionError as e:
            # #29: log full details for operators; post sanitized message to GitHub.
            logger.error(f"GitHub permission denied for {actor}: {e}, correlation_id={cid}")
            await gh.comment(
                number, f"OpsSwarm command rejected (ref: {cid}). Contact your operator."
            )
        except Exception as e:
            cid_ex = cid or generate_correlation_id()
            # #29: never propagate raw exception text to GitHub.
            logger.exception(
                f"OpsSwarm could not process command for #{number}, correlation_id={cid_ex}"
            )
            await gh.comment(
                number,
                f"OpsSwarm encountered an internal error (ref: {cid_ex}). Contact your operator.",
            )
        return {"accepted": True}
    return {"ignored": True}


@app.post("/hooks/monitoring")
async def monitoring_event(
    request: Request,
    x_monitoring_signature: str | None = Header(None),
    api_key: str = Security(api_key_header),
):
    # Authenticate via API Key or Webhook secret
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    body = await request.body()

    is_api_key_valid = (
        bool(api_key)
        and bool(os.environ.get("OPSWARM_API_KEY"))
        and api_key == os.environ.get("OPSWARM_API_KEY")
    )
    is_signature_valid = verify_signature(secret, body, x_monitoring_signature)

    if not is_api_key_valid and not is_signature_valid:
        raise HTTPException(status_code=403, detail="Could not validate credentials")

    payload = await request.json()
    title = payload.get("title") or f"[Incident] {payload.get('service', 'unknown service')}"
    body = f"""## Incident\n\n### Service\n{payload.get("service", "unknown")}\n\n### Symptoms\n{payload.get("symptom", "Monitoring alert")}\n\n### Customer impact\n{payload.get("customer_impact", "unknown")}\n\n### Environment\n{payload.get("environment", "production")}\n\n### Observed since\n{payload.get("observed_since", "unknown")}\n\n### Additional information\nCreated automatically by OpsSwarm monitoring ingress.\n"""
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
