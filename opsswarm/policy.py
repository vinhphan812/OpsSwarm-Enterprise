from __future__ import annotations

from pathlib import Path
from typing import cast

from .models import RecoveryPlan, RemediationOption, Risk
from .registry import _RISK_ORDER, CapabilityRegistry, RegistryResult
from .trusted_classification import classify_trusted_operation

# Re-export so callers don't need a second import
__all__ = ["CapabilityRegistry", "PolicyEngine", "RegistryResult"]


class PolicyEngine:
    """Deterministic approval policy for remediation options.

    The effective risk of an operation is decided by operator-owned sources
    only (ADR-013, ADR-032):

      1. a deny-level destructive marker detected by the trusted classifier
         always wins and can never be downgraded by a registry match or a
         model label;
      2. a capability-registry match is authoritative — it may raise *and*
         lower the model-supplied label (ADR-013 D3);
      3. otherwise the trusted classifier decides: a declared operation
         identity may be read-only or safe, an unrecognised operation is
         treated as risky and therefore requires human approval;
      4. a model-supplied risk label may only raise the resolved risk.

    A model-supplied label is never an authorisation.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg.get("policy", {})
        # Lazily load the capability registry from the path configured in
        # capability_registry.path (resolved relative to the config file's parent).
        reg_path: str | None = cfg.get("capability_registry", {}).get("path")
        self._registry_required = bool(cfg.get("capability_registry", {}).get("required", False))
        self._registry: CapabilityRegistry | None = None
        if reg_path is not None:
            # Use the cwd as base for relative paths (same as config loading)
            p = _resolve_registry_path(reg_path)
            self._registry = CapabilityRegistry.load(p)
        if self._registry_required and self._registry is None:
            raise ValueError(f"Required capability registry is missing or unreadable: {reg_path}")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def action(self, risk: Risk) -> str:
        return self.cfg.get(risk.value, "DENY")

    def classify_operation(self, command: str | None) -> Risk:
        """Legacy free-text heuristic helper, kept for backward compatibility.

        It is no longer part of the risk-resolution path: the trusted
        classifier in `opsswarm.trusted_classification` governs registry
        misses (ADR-032).
        """
        if not command:
            return Risk.RISKY_WRITE
        normalized = command.lower().strip()
        if "patch /admin/" in normalized:
            return Risk.DESTRUCTIVE
        if "patch" in normalized:
            return Risk.SAFE_WRITE
        return Risk.RISKY_WRITE

    def classify_plan(self, plan: RecoveryPlan) -> tuple[str, str]:
        """Classify a plan; the model risk is only a lower bound on the risk."""
        if plan.requires_business_input:
            return "INPUT", plan.business_input_question or "Business input required"
        if not plan.options:
            return "DENY", "No remediation options"
        if len(plan.options) > 1:
            return "DECISION", "Multiple materially different remediation options"
        option = plan.options[0]
        effective, _, _ = self.resolve_effective_risk_for_option(
            option.id, option.description, option.risk, option.capabilities
        )
        action = self.action(effective)
        if action == "AUTO" and not self.authorises_autonomous_execution(option):
            return "APPROVAL", "Operation identity is not declared by an operator allow-list"
        if action == "AUTO":
            return "AUTO", "Trusted operation and policy allow autonomous execution"
        if action == "HUMAN_APPROVAL":
            return "APPROVAL", f"Policy requires human approval ({effective.value})"
        return "DENY", f"Policy denies {effective.value}"

    def authorises_autonomous_execution(self, option: RemediationOption) -> bool:
        """Return True when a trusted source authorises autonomous execution.

        A capability-registry match always authorises. A classifier result
        authorises only when the operation carries an explicitly declared
        operation identity; an unrecognised operation is never authorised and
        must go through a human approval gate (ADR-032).
        """
        _, registry_result, _ = self.resolve_effective_risk_for_option(
            option.id, option.description, option.risk, option.capabilities
        )
        if registry_result is not None and registry_result.matched:
            return True
        return classify_trusted_operation(
            option.description, option.capabilities
        ).declared_operation

    # ------------------------------------------------------------------ #
    # ADR-013 registry integration
    # ------------------------------------------------------------------ #

    @property
    def registry(self) -> CapabilityRegistry | None:
        """The loaded capability registry, or None if not configured."""
        return self._registry

    def resolve_effective_risk(
        self,
        option: RecoveryPlan | RemediationOption | None,
        model_risk: Risk,
    ) -> tuple[Risk, RegistryResult | None, Risk | None]:
        """Determine the effective risk for a remediation option.

        Returns:
            (effective_risk, registry_result, classified_risk)
            registry_result is the registry lookup result (non-None when a
            registry is configured, even when no rule matched).
            classified_risk is the trusted classifier result, or None when a
            registry match decided the risk.

        Evidence field "S6.capability_override" is recorded by the caller using
        the returned RegistryResult and classified_risk.
        """
        selected = _select_option(option)
        if selected is None:
            return self.resolve_effective_risk_for_option("", "", model_risk)
        return self.resolve_effective_risk_for_option(
            str(getattr(selected, "id", "classification") or "classification"),
            str(getattr(selected, "description", "") or ""),
            model_risk,
            _capability_list(getattr(selected, "capabilities", None)),
        )

    def resolve_effective_risk_for_option(
        self,
        option_id: str,
        option_description: str,
        model_risk: Risk,
        capabilities: list[str] | None = None,
    ) -> tuple[Risk, RegistryResult | None, Risk | None]:
        """Resolve effective risk for a standalone RemediationOption.

        Precedence (ADR-013 D3, ADR-032):

          1. a capability-registry match is authoritative and may raise or
             lower the model-supplied label;
          2. a destructive marker found by the trusted classifier always
             wins — no registry match and no model label can downgrade it;
          3. otherwise the trusted classifier decides, and an unrecognised
             operation is risky (human approval) rather than model-decided;
          4. the model-supplied label may only raise the resolved risk.
        """
        trusted = classify_trusted_operation(option_description, capabilities or [])
        classified_risk = trusted.effective_risk

        registry_result: RegistryResult | None = None
        if self._registry is not None:
            registry_result = self._registry.lookup(option_description)

        if registry_result is not None and registry_result.matched:
            # The registry is operator-owned and authoritative on a match
            # (ADR-013 D3): it may raise *and* lower the model-supplied label.
            effective = registry_result.registry_risk
            assert effective is not None
            if trusted.deny_level:
                # ADR-032: a destructive operation is never re-authorised by an
                # allow-list entry, no matter what the registry declares.
                effective = Risk.DESTRUCTIVE
            return effective, registry_result, None

        if classified_risk == Risk.DESTRUCTIVE:
            # A destructive classification is never downgraded by a registry
            # match or by the model-supplied label.
            effective = classified_risk
            if _RISK_ORDER.get(model_risk, -1) > _RISK_ORDER.get(effective, -1):
                effective = model_risk
            return effective, registry_result, classified_risk

        effective = classified_risk
        if _RISK_ORDER.get(model_risk, -1) > _RISK_ORDER.get(effective, -1):
            effective = model_risk
        return effective, registry_result, classified_risk

    def resolve_effective_risk_plan(
        self,
        plan: RecoveryPlan,
        model_risk: Risk,
    ) -> tuple[Risk, RegistryResult | None, Risk | None]:
        """Resolve effective risk for a RecoveryPlan (uses recommended or first option)."""
        return self.resolve_effective_risk(plan, model_risk)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_option(option: RecoveryPlan | RemediationOption | None) -> RemediationOption | None:
    """Return the recommended (or first) option of a plan, or the option itself."""
    if option is None:
        return None
    options = getattr(option, "options", None)
    if options is None:
        return cast(RemediationOption, option)
    if not options:
        return None
    recommended = getattr(option, "recommended_option", None)
    selected = next(
        (o for o in options if getattr(o, "id", None) == recommended),
        options[0],
    )
    return cast(RemediationOption, selected)


def _capability_list(capabilities: object) -> list[str]:
    """Return a plain list of capability strings, ignoring malformed input."""
    if not capabilities or not isinstance(capabilities, (list, tuple, set)):
        return []
    return [str(cap) for cap in capabilities]


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
