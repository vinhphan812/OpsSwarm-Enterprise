from __future__ import annotations

from .models import Risk, RecoveryPlan


class PolicyEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg.get("policy", {})

    def action(self, risk: Risk) -> str:
        return self.cfg.get(risk.value, "DENY")

    def classify_operation(self, command: str | None) -> Risk:
        if not command:
            return Risk.RISKY_WRITE
        if "patch /admin/" in command:
            return Risk.DESTRUCTIVE
        if "patch" in command:
            return Risk.SAFE_WRITE
        return Risk.RISKY_WRITE

    def classify_plan(self, plan: RecoveryPlan) -> tuple[str, str]:
        if plan.requires_business_input:
            return "INPUT", plan.business_input_question or "Business input required"
        if not plan.options:
            return "DENY", "No remediation options"
        if len(plan.options) > 1:
            return "DECISION", "Multiple materially different remediation options"
        opt = plan.options[0]
        action = self.action(opt.risk)
        if action == "AUTO":
            return "AUTO", "Policy allows autonomous execution"
        if action == "HUMAN_APPROVAL":
            return "APPROVAL", "Policy requires human approval"
        return "DENY", f"Policy denies {opt.risk.value}"
