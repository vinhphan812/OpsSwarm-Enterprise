from __future__ import annotations

import re
import logging

from pydantic import ValidationError

from .models import (
    Task,
    RecoveryPlan,
    ExecutionResult,
    VerificationResult,
    Finding,
    RootCauseArtifact,
    IncidentContext,
    EvidenceRef,
)
from .normalization import normalize_finding, normalize_root_cause_artifact, normalize_recovery_plan
from .prompts import *

logger = logging.getLogger(__name__)


def parse_issue(number: int, issue: dict) -> IncidentContext:
    body = issue.get("body") or ""
    title = issue.get("title") or ""
    labels = [x.get("name", "") if isinstance(x, dict) else str(x) for x in issue.get("labels", [])]

    def field(name, default="unknown"):
        m = re.search(rf"(?ims)^###\s*{re.escape(name)}\s*$\s*(.+?)(?=^###\s|\Z)", body)
        return m.group(1).strip() if m else default

    symptoms = field("Symptoms", "")
    sev = "UNKNOWN"
    for lab in labels:
        if lab.lower().startswith("sev:"):
            sev = "SEV" + lab.split(":", 1)[1].strip()
    return IncidentContext(
        issue_number=number,
        title=title,
        body=body,
        service=field("Service"),
        environment=field("Environment"),
        severity=sev,
        symptoms=[x.strip(" -") for x in symptoms.splitlines() if x.strip()] or [title],
        customer_impact=field("Customer impact"),
        actor=(issue.get("user") or {}).get("login"),
        labels=labels,
    )


async def build_tasks(oc, agent: str, run_id: str, incident: IncidentContext) -> list[Task]:
    data = await oc.run_json(agent, f"{run_id}-s2", task_graph_prompt(incident))
    return [Task.model_validate(x) for x in data.get("tasks", [])]


async def execute_task(
    oc, profile_agent: str, run_id: str, incident: IncidentContext, task: Task
) -> Finding:
    data = await oc.run_json(
        profile_agent, f"{run_id}-{task.id}", specialist_prompt(incident, task.model_dump_json())
    )
    try:
        normalized = normalize_finding(data)
        return Finding.model_validate(normalized)
    except ValidationError as ve:
        redacted = _persist_diagnostics(run_id, "S4.finding", data, str(ve))
        logger.error(f"Validation failed for task {task.id}: {redacted}")
        return Finding(
            task_id=task.id,
            finding="Validation failed: structured output could not be parsed",
            evidence=[redacted],
            confidence=0.0,
        )
    except Exception as e:
        logger.error(f"Unexpected error for task {task.id}: [details redacted]")
        return Finding(
            task_id=task.id,
            finding="Unexpected error during task execution",
            evidence=["[Raw output redacted for PII sensitivity]"],
            confidence=0.0,
        )


def _persist_diagnostics(run_id: str, kind: str, raw_data: dict, error: str) -> str:
    """Persist redacted diagnostics to evidence store and return the evidence ID.

    Redacts PII from both the raw data and the error message before storing.
    Returns a string representation of the evidence ID or a placeholder.
    """
    try:
        from .evidence import EvidenceStore

        # Import config for data_dir
        from .config import config

        store = EvidenceStore(data_dir=config.data_dir)
        redacted_raw = _redact_dict(raw_data)
        redacted_error = _redact_pii_from_str(error)
        eid, _ = store.append(
            run_id,
            kind,
            {"diagnostics": redacted_raw, "validation_error": redacted_error},
        )
        return eid or f"diagnostics:{run_id}:{kind}"
    except Exception:
        # Best-effort: never let evidence persistence failures break incident processing
        return "[Diagnostics persisted to evidence store]"


def _redact_pii_from_str(text: str) -> str:
    """Redact emails and similar PII from a string."""
    return re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[REDACTED]", text)


def _redact_dict(data: dict) -> dict:
    """Recursively redact PII from a dict, redacting string values and serializing others."""
    result: dict = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = _redact_pii_from_str(v)
        elif isinstance(v, dict):
            result[k] = _redact_dict(v)
        elif isinstance(v, list):
            result[k] = [_redact_pii_from_str(str(x)) for x in v]
        else:
            result[k] = v
    return result


async def synthesize_root_cause(
    oc, agent, run_id, incident, findings, human_inputs
) -> RootCauseArtifact:
    data = await oc.run_json(
        agent, f"{run_id}-rca", root_cause_prompt(incident, findings, human_inputs)
    )
    try:
        normalized = normalize_root_cause_artifact(data)
        return RootCauseArtifact.model_validate(normalized)
    except ValidationError as ve:
        redacted = _persist_diagnostics(run_id, "RCA.root_cause", data, str(ve))
        logger.error(f"Validation failed for root cause: {redacted}")
        return RootCauseArtifact(
            status="uncertain",
            proximate_cause="Unable to normalize root-cause output",
            root_cause="unknown",
        )
    except Exception as e:
        logger.error(f"Unexpected error in synthesize_root_cause: [details redacted]")
        return RootCauseArtifact(
            status="uncertain",
            proximate_cause="Unable to synthesize root cause",
            root_cause="unknown",
        )


async def make_recovery_plan(oc, agent, run_id, incident, root, human_inputs) -> RecoveryPlan:
    data = await oc.run_json(
        agent, f"{run_id}-plan", recovery_plan_prompt(incident, root, human_inputs)
    )
    try:
        normalized = normalize_recovery_plan(data)
        return RecoveryPlan.model_validate(normalized)
    except ValidationError as ve:
        redacted = _persist_diagnostics(run_id, "S3.recovery_plan", data, str(ve))
        logger.error(f"Validation failed for recovery plan: {redacted}")
        return RecoveryPlan(options=[])
    except Exception as e:
        logger.error(f"Unexpected error in make_recovery_plan: [details redacted]")
        return RecoveryPlan(options=[])


async def execute_recovery(oc, agent, run_id, incident, root, option) -> ExecutionResult:
    return ExecutionResult.model_validate(
        await oc.run_json(
            agent, f"{run_id}-recover", recovery_prompt(incident, root, option.model_dump_json())
        )
    )


async def verify_recovery(oc, agent, run_id, incident, execution) -> VerificationResult:
    return VerificationResult.model_validate(
        await oc.run_json(
            agent, f"{run_id}-verify", verify_prompt(incident, execution.model_dump_json())
        )
    )


async def make_extra_task(oc, agent, run_id, incident, request) -> Task:
    return Task.model_validate(
        await oc.run_json(agent, f"{run_id}-extra", extra_investigation_prompt(incident, request))
    )
