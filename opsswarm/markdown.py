from __future__ import annotations
from .models import *

def investigation_started(run:RunRecord)->str:
    return f"""## OpsSwarm — Investigation started\n\nRun: `{run.run_id}`\nState: `{run.state.value}`\n\n### Investigation tasks\n""" + "\n".join(f"- [ ] `{t.id}` {t.type.value}: {t.objective} → **{t.profile}**" for t in run.tasks)

def diagnosis(run:RunRecord)->str:
    r=run.root_cause
    return f"""## OpsSwarm — Diagnosis\n\n### Proximate cause\n{r.proximate_cause}\n\n### Root cause\n{r.root_cause}\n\n### Confidence\n{r.confidence:.2f}\n\n### Causal chain\n""" + "\n".join(f"- {x}" for x in r.causal_chain) + "\n\n### Evidence\n" + "\n".join(f"- `{x}`" for x in r.evidence_refs)

def decision_request(run:RunRecord)->str:
    d=run.decision
    lines=["## ⚠ Human decision required", "", d.reason, ""]
    if d.question: lines += ["### Input required", d.question, "", "Respond with:", "`/opsswarm provide <information>`"]
    if d.options:
        lines += ["### Options"]
        for o in d.options:
            lines += [f"- **{o.id}** — {o.description}", f"  - Risk: `{o.risk.value}`", f"  - Estimated recovery: {o.estimated_recovery or 'unknown'}"]
        lines += ["",f"Recommended: `{d.recommended_option or 'none'}`","", "Respond with one of:", "`/opsswarm approve <option-id>`", "`/opsswarm investigate <request>`", "`/opsswarm reject`", "`/opsswarm abort`"]
    return "\n".join(lines)

def resolved(run:RunRecord)->str:
    return f"""## ✅ Incident resolved\n\nRun: `{run.run_id}`\nStatus: `RESOLVED`\n\n### Root cause\n{run.root_cause.root_cause if run.root_cause else 'unknown'}\n\n### Recovery\n{run.execution.summary if run.execution else 'n/a'}\n\n### Independent verification\n{run.verification.summary if run.verification else 'n/a'}\n\nConfidence: {run.verification.confidence if run.verification else 0:.2f}\n"""

def postmortem(run:RunRecord)->str:
    r=run.root_cause
    return f"""## Postmortem\n\n### Impact\n{run.incident.customer_impact if run.incident else 'unknown'}\n\n### Proximate cause\n{r.proximate_cause if r else 'unknown'}\n\n### Root cause\n{r.root_cause if r else 'unknown'}\n\n### Lessons / corrective actions\n""" + ("\n".join(f"- {x}" for x in (r.corrective_actions if r else [])) or "- None proposed")
