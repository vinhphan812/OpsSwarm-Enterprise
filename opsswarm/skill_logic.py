from __future__ import annotations

import re
import logging

from .models import Task, RecoveryPlan, ExecutionResult, VerificationResult, Finding, RootCauseArtifact, IncidentContext
from .normalization import (
    normalize_finding,
    normalize_root_cause_artifact,
    normalize_recovery_plan
)
from .prompts import *

logger = logging.getLogger(__name__)


def parse_issue(number: int, issue: dict) -> IncidentContext:
    body = issue.get("body") or "";
    title = issue.get("title") or ""
    labels = [x.get("name", "") if isinstance(x, dict) else str(x) for x in issue.get("labels", [])]

    def field(name, default="unknown"):
        m = re.search(rf"(?ims)^###\s*{re.escape(name)}\s*$\s*(.+?)(?=^###\s|\Z)", body)
        return m.group(1).strip() if m else default

    symptoms = field("Symptoms", "")
    sev = "UNKNOWN"
    for lab in labels:
        if lab.lower().startswith("sev:"): sev = "SEV" + lab.split(":", 1)[1].strip()
    return IncidentContext(issue_number=number, title=title, body=body, service=field("Service"),
                           environment=field("Environment"), severity=sev,
                           symptoms=[x.strip(" -") for x in symptoms.splitlines() if x.strip()] or [title],
                           customer_impact=field("Customer impact"),
                           actor=(issue.get("user") or {}).get("login"), labels=labels)


async def build_tasks(oc, agent: str, run_id: str, incident: IncidentContext) -> list[Task]:
    data = await oc.run_json(agent, f"{run_id}-s2", task_graph_prompt(incident))
    return [Task.model_validate(x) for x in data.get("tasks", [])]


async def execute_task(oc, profile_agent: str, run_id: str, incident: IncidentContext, task: Task) -> Finding:
    data = await oc.run_json(profile_agent, f"{run_id}-{task.id}", specialist_prompt(incident, task.model_dump_json()))
    try:
        normalized = normalize_finding(data)
        return Finding.model_validate(normalized)
    except Exception as e:
        logger.error(f"Validation failed for task {task.id}: {e}")
        # Add basic evidence for validation failure
        return Finding(
            task_id=task.id,
            finding=f"Validation failed: {str(e)}",
            evidence=["[Raw output redacted for PII sensitivity]"],
            confidence=0.0
        )


async def synthesize_root_cause(oc, agent, run_id, incident, findings, human_inputs) -> RootCauseArtifact:
    data = await oc.run_json(agent, f"{run_id}-rca", root_cause_prompt(incident, findings, human_inputs))
    try:
        normalized = normalize_root_cause_artifact(data)
        return RootCauseArtifact.model_validate(normalized)
    except Exception as e:
        logger.error(f"Validation failed for root cause: {e}")
        return RootCauseArtifact(
            status="uncertain",
            proximate_cause="Unable to normalize root-cause output",
            root_cause="unknown",
        )


async def make_recovery_plan(oc, agent, run_id, incident, root, human_inputs) -> RecoveryPlan:
    data = await oc.run_json(agent, f"{run_id}-plan", recovery_plan_prompt(incident, root, human_inputs))
    try:
        normalized = normalize_recovery_plan(data)
        return RecoveryPlan.model_validate(normalized)
    except Exception as e:
        logger.error(f"Validation failed for recovery plan: {e}")
        return RecoveryPlan(options=[])


async def execute_recovery(oc, agent, run_id, incident, root, option) -> ExecutionResult:
    return ExecutionResult.model_validate(
        await oc.run_json(agent, f"{run_id}-recover", recovery_prompt(incident, root, option.model_dump_json())))


async def verify_recovery(oc, agent, run_id, incident, execution) -> VerificationResult:
    return VerificationResult.model_validate(
        await oc.run_json(agent, f"{run_id}-verify", verify_prompt(incident, execution.model_dump_json())))


async def make_extra_task(oc, agent, run_id, incident, request) -> Task:
    return Task.model_validate(
        await oc.run_json(agent, f"{run_id}-extra", extra_investigation_prompt(incident, request)))
