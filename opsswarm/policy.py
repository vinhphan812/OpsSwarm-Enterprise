from __future__ import annotations

from pathlib import Path

from .models import Risk, RecoveryPlan
from .registry import CapabilityRegistry, RegistryResult, _RISK_ORDER

# Re-export so callers don't need a second import
__all__ = ["PolicyEngine", "CapabilityRegistry", "RegistryResult"]


class PolicyEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg.get("policy", {})
        # Lazily load the capability registry from the path configured in
        # capability_registry.path (resolved relative to the config file's parent).
        reg_path: str | None = cfg.get("capability_registry", {}).get("path")
        self._registry: CapabilityRegistry | None = None
        if reg_path is not None:
            # Use the cwd as base for relative paths (same as config loading)
            p = _resolve_registry_path(reg_path)
            self._registry = CapabilityRegistry.load(p)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def action(self, risk: Risk) -> str:
        return self.cfg.get(risk.value, "DENY")

    def classify_operation(self, command: str | None) -> Risk:
        """Heuristic classification — preserved as a second layer for unmatched ops."""
        if not command:
            return Risk.RISKY_WRITE
        normalized = command.lower().strip()
        if "patch /admin/" in normalized:
            return Risk.DESTRUCTIVE
        if "patch" in normalized:
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

    # ------------------------------------------------------------------ #
    # ADR-013 registry integration
    # ------------------------------------------------------------------ #

    @property
    def registry(self) -> CapabilityRegistry | None:
        """The loaded capability registry, or None if not configured."""
        return self._registry

    def resolve_effective_risk(
        self,
        option: RecoveryPlan | None,
        model_risk: Risk,
    ) -> tuple[Risk, RegistryResult | None, Risk | None]:
        """Determine the effective risk for a remediation option.

        Precedence (ADR-013 D3):
          1. registry lookup → use registry risk on match (always wins)
          2. classify_operation() heuristic → use classified risk if it escalates
          3. model-supplied label → fallback

        Returns:
            (effective_risk, registry_result, classified_risk)
            registry_result is non-None only when a registry rule matched.
            classified_risk is the classify_operation() result (for evidence).

        Evidence field "S6.capability_override" is recorded by the caller using
        the returned RegistryResult and classified_risk.
        """
        registry_result: RegistryResult | None = None
        classified_risk: Risk | None = None

        # Step 1: registry lookup
        description: str = ""
        if option and option.options:
            description = option.options[0].description

        if self._registry is not None:
            registry_result = self._registry.lookup(description)
            if registry_result.matched:
                effective = registry_result.registry_risk
                assert effective is not None
                return effective, registry_result, classified_risk

        # Step 2: heuristic escalation
        classified_risk = self.classify_operation(description)
        if _RISK_ORDER.get(classified_risk, -1) > _RISK_ORDER.get(model_risk, -1):
            return classified_risk, registry_result, classified_risk

        # Step 3: model label
        return model_risk, registry_result, classified_risk

    def resolve_effective_risk_for_option(
        self,
        option_id: str,
        option_description: str,
        model_risk: Risk,
    ) -> tuple[Risk, RegistryResult | None, Risk | None]:
        """Resolve effective risk for a standalone RemediationOption.

        This overload avoids constructing a RecoveryPlan when only the option
        fields are available (e.g., during approve command processing).
        """
        registry_result: RegistryResult | None = None
        classified_risk: Risk | None = None

        # Step 1: registry lookup
        if self._registry is not None:
            registry_result = self._registry.lookup(option_description)
            if registry_result.matched:
                effective = registry_result.registry_risk
                assert effective is not None
                return effective, registry_result, classified_risk

        # Step 2: heuristic escalation
        classified_risk = self.classify_operation(option_description)
        if _RISK_ORDER.get(classified_risk, -1) > _RISK_ORDER.get(model_risk, -1):
            return classified_risk, registry_result, classified_risk

        # Step 3: model label
        return model_risk, registry_result, classified_risk

    def resolve_effective_risk_plan(
        self,
        plan: RecoveryPlan,
        model_risk: Risk,
    ) -> tuple[Risk, RegistryResult | None, Risk | None]:
        """Resolve effective risk for a RecoveryPlan (uses recommended or first option)."""
        if plan.options:
            opt = next(
                (o for o in plan.options if o.id == plan.recommended_option),
                plan.options[0],
            )
            return self.resolve_effective_risk_for_option(opt.id, opt.description, model_risk)
        return self.resolve_effective_risk(None, model_risk)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_registry_path(path: str) -> str | None:
    """Resolve a registry path from config.

    Supports:
      - Absolute paths: returned as-is.
      - Relative paths: resolved from the repo root (cwd), consistent with
        how config.py resolves relative config paths.
      - None / empty: returns None.
    """
    if not path:
        return None
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str(p)  # Relative to cwd (repo root)
