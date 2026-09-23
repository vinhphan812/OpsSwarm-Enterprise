from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, Request, Header, HTTPException

from .commands import parse_command
from .config import load_config
from .github_client import GitHubClient
from .openclaw import OpenClawClient
from .orchestrator import Orchestrator
from .webhook import verify_signature

cfg = load_config()
gh = GitHubClient(os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPO", cfg.get("repo", "")))
oc = OpenClawClient(os.environ.get("OPSWARM_OPENCLAW_BIN", "openclaw"), int(os.environ.get("OPSWARM_OPENCLAW_TIMEOUT",
                                                                                           cfg.get("openclaw", {}).get(
                                                                                               "timeout_seconds",
                                                                                               600))))
engine = Orchestrator(cfg, gh, oc, os.environ.get("OPSWARM_DATA_DIR", "runtime-data"))
app = FastAPI(title="OpsSwarm Enterprise OpenClaw+GitHub", version="2.1.0")


@app.get("/health")
async def health(): return {"ok": True, "version": "2.1.0", "architecture": "openclaw+github"}


@app.get("/runs")
async def runs(): return [r.model_dump(mode="json") for r in engine.runs.values()]


@app.get("/runs/{issue_number}")
async def run(issue_number: int):
    r = engine.runs.get(issue_number)
    if not r: raise HTTPException(404, "No run for issue")
    return r.model_dump(mode="json")


@app.get("/runs/{issue_number}/evidence")
async def evidence(issue_number: int):
    r = engine.runs.get(issue_number)
    if not r: raise HTTPException(404, "No run for issue")
    return engine.ev.list(r.run_id)


@app.get("/runs/{issue_number}/checkpoint")
async def get_checkpoint(issue_number: int):
    """Get the last checkpoint for a run."""
    r = engine.runs.get(issue_number)
    if not r: raise HTTPException(404, "No run for issue")
    checkpoint = engine.ev.get_last_checkpoint(r.run_id)
    if not checkpoint:
        return {"has_checkpoint": False, "checkpoint": None}
    return {"has_checkpoint": True, "checkpoint": checkpoint}


@app.post("/runs/{issue_number}/resume")
async def resume_run(issue_number: int):
    """Resume a run from its last checkpoint."""
    r = engine.runs.get(issue_number)
    if not r: raise HTTPException(404, "No run for issue")

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
async def github_webhook(request: Request, x_github_event: str | None = Header(None),
                         x_hub_signature_256: str | None = Header(None), x_github_delivery: str | None = Header(None)):
    body = await request.body();
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not verify_signature(secret, body, x_hub_signature_256): raise HTTPException(401, "Invalid webhook signature")
    data = await request.json()
    if x_github_event == "issues" and data.get("action") == "opened":
        number = int(data["issue"]["number"]);
        asyncio.create_task(engine.start_issue(number, x_github_delivery));
        return {"accepted": True, "issue": number}
    if x_github_event == "issue_comment" and data.get("action") == "created":
        number = int(data["issue"]["number"]);
        actor = data["comment"]["user"]["login"];
        text = data["comment"].get("body") or ""
        # Extract comment ID for idempotency
        comment_id = str(data["comment"].get("id", ""))
        permission = await gh.permission(actor)
        try:
            await engine.handle_comment(number, actor, text, permission, parse_command(text), comment_id,
                                        x_github_delivery)
        except PermissionError as e:
            await gh.comment(number, f"OpsSwarm command rejected: {e}")
        except Exception as e:
            await gh.comment(number, f"OpsSwarm could not process the command: `{type(e).__name__}: {e}`")
        return {"accepted": True}
    return {"ignored": True}


@app.post("/hooks/monitoring")
async def monitoring_event(payload: dict):
    title = payload.get("title") or f"[Incident] {payload.get('service', 'unknown service')}"
    body = f"""## Incident\n\n### Service\n{payload.get('service', 'unknown')}\n\n### Symptoms\n{payload.get('symptom', 'Monitoring alert')}\n\n### Customer impact\n{payload.get('customer_impact', 'unknown')}\n\n### Environment\n{payload.get('environment', 'production')}\n\n### Observed since\n{payload.get('observed_since', 'unknown')}\n\n### Additional information\nCreated automatically by OpsSwarm monitoring ingress.\n"""
    labels = list(dict.fromkeys(
        cfg.get("labels", {}).get("base", ["opsswarm", "incident"]) + [payload.get("severity_label", "sev:2")]))
    issue = await gh.create_issue(title, body, labels);
    number = int(issue["number"]);
    asyncio.create_task(engine.start_issue(number));
    return {"accepted": True, "issue_number": number}
