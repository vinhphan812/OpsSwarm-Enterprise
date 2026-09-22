from __future__ import annotations
import json
from .models import IncidentContext, Finding, RootCauseArtifact

JSON_ONLY="Return ONLY valid JSON. No markdown fences and no prose outside JSON."

def task_graph_prompt(incident: IncidentContext) -> str:
    return f'''You are OpsSwarm S2 TaskGraph. Create the minimum investigation DAG needed to diagnose this incident.
Allowed task types: OBSERVE, INVESTIGATE, DIAGNOSE. Do not create REMEDIATE tasks yet.
Allowed profiles: observability-investigator, application-investigator, infrastructure-investigator, database-investigator.
All initial tasks MUST be read-only. Use dependencies and parallel work when useful.
Return an object with key "tasks"; each task has: id,type,objective,profile,required_capabilities,risk,depends_on,parallelizable,expected_output,status.
Risk must be "read".
{JSON_ONLY}
Incident:\n{incident.model_dump_json(indent=2)}'''

def specialist_prompt(incident: IncidentContext, task_json: str) -> str:
    return f'''You are an OpsSwarm specialist working on one bounded incident task.
Do only the assigned task. Respect READ_ONLY scope. Do not perform remediation or writes.
Use available OpenClaw tools to gather real evidence. If a tool is unavailable, say so rather than fabricate evidence.
Return JSON with: task_id, finding, evidence (array of concrete refs/observations), hypothesis, confidence (0..1), recommended_next_action, raw (object).
{JSON_ONLY}
Incident:\n{incident.model_dump_json(indent=2)}\nTask:\n{task_json}'''

def root_cause_prompt(incident: IncidentContext, findings: list[Finding], human_inputs: list[dict]) -> str:
    return f'''You are OpsSwarm root-cause synthesis. Distinguish proximate cause from root cause.
Do not claim confirmed root cause unless evidence supports it. Never fabricate enterprise facts.
Return JSON fields: status (confirmed|uncertain), proximate_cause, root_cause, causal_chain[], evidence_refs[], confidence, remediation_options[], human_input_question|null, corrective_actions[].
If missing business knowledge prevents a sound decision, set status=uncertain and ask one concrete human_input_question.
{JSON_ONLY}
Incident:\n{incident.model_dump_json(indent=2)}\nFindings:\n{json.dumps([f.model_dump() for f in findings],ensure_ascii=False,default=str)}\nHuman inputs:\n{json.dumps(human_inputs,ensure_ascii=False)}'''

def recovery_plan_prompt(incident: IncidentContext, root: RootCauseArtifact, human_inputs:list[dict]) -> str:
    return f'''You are OpsSwarm S3 recovery planner. Propose only evidence-supported remediation options.
Return JSON with: options[], recommended_option|null, confidence, requires_business_input, business_input_question|null.
Each option: id,description,profile="recovery-responder",risk(read|safe_write|risky_write|destructive),estimated_recovery|null,rationale,capabilities[].
Use destructive only when the action is actually destructive. If key business constraints are missing, set requires_business_input=true.
{JSON_ONLY}
Incident:\n{incident.model_dump_json(indent=2)}\nRoot cause:\n{root.model_dump_json(indent=2)}\nHuman inputs:\n{json.dumps(human_inputs,ensure_ascii=False)}'''

def recovery_prompt(incident:IncidentContext, root:RootCauseArtifact, option_json:str) -> str:
    return f'''You are OpsSwarm recovery-responder. Execute ONLY the authorized remediation option below using available OpenClaw tools.
Do not broaden scope. Preserve idempotency where supported. If transport becomes ambiguous after a write, do not blindly repeat it.
Return JSON: option_id,success,summary,evidence[],ambiguous,raw.
{JSON_ONLY}
Incident:\n{incident.model_dump_json(indent=2)}\nRoot cause:\n{root.model_dump_json(indent=2)}\nAuthorized option:\n{option_json}'''

def verify_prompt(incident:IncidentContext, execution_json:str) -> str:
    return f'''You are OpsSwarm S7 independent verifier. Independently check whether customer/business service health is restored.
Do not accept the executor's success claim as proof. Use read-only evidence from metrics, health checks, logs or service state.
Return JSON: verified,summary,evidence[],confidence,raw.
{JSON_ONLY}
Incident:\n{incident.model_dump_json(indent=2)}\nExecution result (context only; not proof):\n{execution_json}'''

def extra_investigation_prompt(incident:IncidentContext, request:str)->str:
    return f'''You are OpsSwarm S2. Convert this human-requested additional investigation into exactly one READ_ONLY task.
Choose one profile from observability-investigator, application-investigator, infrastructure-investigator, database-investigator.
Return a task object with id="HX1", type="INVESTIGATE", objective, profile, required_capabilities[], risk="read", depends_on=[], parallelizable=false, expected_output="Finding", status="PENDING".
{JSON_ONLY}\nIncident:\n{incident.model_dump_json(indent=2)}\nHuman request:\n{request}'''
