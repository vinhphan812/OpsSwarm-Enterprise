"""ADR-013: Trusted Capability Registry.

Implements deterministic approval via an operator-maintained YAML registry that
overrides LLM-supplied risk labels. The registry always wins on a match; the
classify_operation() heuristic is preserved as a second escalation layer for
unmatched operations.

Design decisions (ADR-013):
  D1: Registry path configurable via config/capability-registry.yaml.
  D2: YAML schema with version, ordered rules, pattern + pattern_mode.
  D3: Registry always wins on match; classify_operation preserved as fallback.
  D4: Git-tracked, PR-reviewed, startup validation, no hot reload.
  D5: Missing file → warning + model label; invalid YAML → ValueError at startup.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Risk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

_RISK_ORDER: dict[Risk, int] = {
    Risk.READ: -1,
    Risk.SAFE_WRITE: 0,
    Risk.RISKY_WRITE: 1,
    Risk.DESTRUCTIVE: 2,
}


@dataclass
class RegistryRule:
    """A single rule in the capability registry."""

    id: str
    canonical_operation: str
    description: str
    pattern: str
    risk: Risk
    pattern_mode: str = "contains"  # "contains" | "prefix" | "regex"
    rationale: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None

    def matches(self, command: str | None) -> bool:
        """Return True when the normalized command text matches this rule."""
        if command is None:
            return False
        normalized = re.sub(r"\s+", " ", command.lower().strip())
        pattern_lower = self.pattern.lower()
        if self.pattern_mode == "prefix":
            return normalized.startswith(pattern_lower)
        if self.pattern_mode == "regex":
            try:
                return bool(re.search(self.pattern, command, re.IGNORECASE))
            except re.error:
                return False
        # Default: contains
        return pattern_lower in normalized


@dataclass
class RegistryResult:
    """Outcome of a registry lookup."""

    matched: bool
    rule_id: str | None = None
    canonical_operation: str | None = None
    registry_risk: Risk | None = None
    approved_by: str | None = None
    pattern_matched: str | None = None
    pattern_mode: str | None = None


@dataclass
class CapabilityRegistry:
    """Loaded capability registry with auditable lookup and validation.

    Lifecycle (per ADR-013 D4):
      - load()        : parse and validate on startup
      - lookup()      : per-operation query during approval
      - validate()    : raise ValueError on unknown schema version or bad risk
    """

    version: str
    description: str | None
    rules: list[RegistryRule] = field(default_factory=list)

    # ---------------------------------------------------------------------------
    # Loading / factory
    # ---------------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None) -> "CapabilityRegistry | None":
        """Load and validate a capability registry from disk.

        Per ADR-013 D5:
          - File absent or unreadable → None (warn, fall back to model label).
          - Invalid YAML or unknown version → raise ValueError (block startup).
        """
        if path is None:
            return None
        p = Path(path).expanduser()
        if not p.exists():
            logger.warning("[ADR-013] Capability registry not found at %s — using model labels", p)
            return None
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(
                f"[ADR-013] Capability registry at {p} contains invalid YAML: {exc}"
            ) from exc

        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "CapabilityRegistry":
        """Build a CapabilityRegistry from a parsed YAML dict."""
        version = data.get("version")
        if version is None:
            raise ValueError("[ADR-013] Registry is missing required 'version' field")
        if version != "1":
            raise ValueError(
                f"[ADR-013] Unsupported registry schema version {version!r} (only '1' is supported)"
            )

        rules: list[RegistryRule] = []
        rule_ids: set[str] = set()
        for i, entry in enumerate(data.get("rules", [])):
            if "id" not in entry:
                raise ValueError(f"[ADR-013] Rule at index {i} is missing required 'id' field")
            rid = str(entry["id"])
            if rid in rule_ids:
                raise ValueError(f"[ADR-013] Duplicate rule id {rid!r}")
            rule_ids.add(rid)

            # Parse risk (may raise ValueError for unknown values)
            raw_risk = entry.get("risk", "")
            try:
                risk = Risk(raw_risk)
            except ValueError:
                valid = [r.value for r in Risk]
                raise ValueError(
                    f"[ADR-013] Rule {rid!r} has invalid risk {raw_risk!r}; "
                    f"expected one of {valid}"
                )

            # Validate pattern_mode
            pm = entry.get("pattern_mode", "contains")
            if pm not in ("contains", "prefix", "regex"):
                raise ValueError(
                    f"[ADR-013] Rule {rid!r} has invalid pattern_mode {pm!r}; "
                    f"expected 'contains', 'prefix', or 'regex'"
                )

            # Validate pattern is present
            if not entry.get("pattern"):
                raise ValueError(
                    f"[ADR-013] Rule {rid!r} is missing required 'pattern' field"
                )

            rules.append(
                RegistryRule(
                    id=rid,
                    canonical_operation=str(entry.get("canonical_operation", rid)),
                    description=str(entry.get("description", "")),
                    pattern=str(entry["pattern"]),
                    pattern_mode=pm,
                    risk=risk,
                    rationale=entry.get("rationale"),
                    approved_by=entry.get("approved_by"),
                    approved_at=entry.get("approved_at"),
                )
            )

        return cls(
            version=str(version),
            description=data.get("description"),
            rules=rules,
        )

    # ---------------------------------------------------------------------------
    # Lookup
    # ---------------------------------------------------------------------------

    def lookup(self, command: str | None) -> RegistryResult:
        """Return the first matching rule's risk override.

        Per ADR-013 D3: first-match wins (rules are evaluated in declaration order).
        Returns RegistryResult(matched=False) when no rule matches.
        """
        if command is None:
            return RegistryResult(matched=False)
        for rule in self.rules:
            if rule.matches(command):
                return RegistryResult(
                    matched=True,
                    rule_id=rule.id,
                    canonical_operation=rule.canonical_operation,
                    registry_risk=rule.risk,
                    approved_by=rule.approved_by,
                    pattern_matched=rule.pattern,
                    pattern_mode=rule.pattern_mode,
                )
        return RegistryResult(matched=False)

    def is_empty(self) -> bool:
        """Return True when the registry has no rules (degenerate case)."""
        return len(self.rules) == 0

    def rule_count(self) -> int:
        return len(self.rules)
