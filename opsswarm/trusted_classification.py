"""Operator-owned risk classification for autonomous remediation (ADR-032).

The risk label produced by the model is never an authorisation. It may only
*raise* the effective risk of a remediation option; it can never lower it.

The effective risk of a remediation option is decided by operator-owned
sources only:

  1. the capability registry (``config/capability-registry.yaml``) — an
     operator-maintained allow-list/block-list;
  2. this module — a deterministic classifier over the operation identity,
     consisting of the option's declared capabilities (a controlled
     vocabulary) and the operation description.

Free-text descriptions never authorise execution on their own: a description
that matches no operator-declared operation is *unknown* and is routed to a
human approval gate.

Precedence used by ``PolicyEngine``:

  destructive marker  >  registry match  >  declared identity  >  unknown

A destructive marker is evaluated first, so neither a registry allow-list
entry nor a model-supplied label can downgrade a destructive operation.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .models import Risk

__all__ = [
    "READ_OPERATION_IDS",
    "SAFE_OPERATION_IDS",
    "TrustedRisk",
    "classify_trusted_operation",
    "normalise_operation_text",
]


# --------------------------------------------------------------------------- #
# Operator-owned operation vocabulary
# --------------------------------------------------------------------------- #

#: Operation identities that are safe to execute autonomously.
SAFE_OPERATION_IDS: frozenset[str] = frozenset(
    {
        "cache.refresh",
        "cache.clear",
        "deploy.restart",
        "pod.restart",
        "container.restart",
        "kubectl_scale_replicas",
        "kubectl_set_image",
    }
)

#: Operation identities that only read state.
READ_OPERATION_IDS: frozenset[str] = frozenset(
    {
        "metrics.read",
        "observability.read",
        "cluster.read",
        "incident.read",
        "logs.read",
    }
)


# --------------------------------------------------------------------------- #
# Operator-owned pattern tables
# --------------------------------------------------------------------------- #

# Irreversible data loss or namespace destruction. Never executed and never
# approved by a human gate. A match here vetoes any capability-registry
# allow-list entry: no operator allow-list can re-authorise a destructive
# operation.
_DESTRUCTIVE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdrop\s+(database|schema|table|collection|index)\b",
        r"\bdatabase_drop\b",
        r"\bredis_flush\b",
        r"\bkubectl_delete_all\b",
        r"\bnamespace\.delete\b",
        r"\bcluster\.delete\b",
        r"\bdata\.purge\b",
        r"\bflush\s*all\b",
        r"\bflushall\b",
        r"\bflushdb\b",
        r"\btruncate\b",
        r"\brm\s+-rf\b",
        r"\bdelete\s+(namespace|all)\b",
        r"--all\b",
        r"\bpurge\b",
        r"\bdestroy\b",
        r"\bwipe\b",
    )
)


# Privileged administrative mutations. The capability registry classifies
# these as human-approval operations (ADR-013), so a registry match may
# override this classification; without a registry match they are treated as
# destructive.
_ADMIN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bpatch\s+/admin/",
    )
)

# State mutations that a human must authorise.
_RISKY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bkubectl\s+delete\b",
        r"\bdelete\b",
        r"\bpatch\b",
        r"\brollback\b",
        r"\brollout\s+undo\b",
        r"\bterraform\s+apply\b",
        r"\bapply\b",
        r"\bmigrat",
        r"\brestart\s+(service|deployment|statefulset|daemonset|job)\b",
        r"\bforce\b",
        r"\brotate\b",
        r"\bexec\b",
    )
)


@dataclass(frozen=True)
class TrustedRisk:
    """The effective risk of a remediation option, plus its provenance."""

    effective_risk: Risk
    source: str
    reason: str
    declared_operation: bool = False
    """True when the decision came from an explicitly declared operation identity."""

    deny_level: bool = False
    """True for destructive operations that no allow-list entry can re-authorise."""

    @property
    def trusted(self) -> bool:
        """True when a trusted source decided the risk."""
        return self.source in {"registry", "classifier"}


def normalise_operation_text(description: str | None) -> str:
    """Return the operation description used for marker inspection."""
    return (description or "").strip()


def classify_trusted_operation(
    description: str | None,
    capabilities: Sequence[str] | None = None,
) -> TrustedRisk:
    """Classify a remediation option using operator-owned rules only.

    Destructive and risky markers are inspected across both the description
    and the declared capabilities, so a benign verb cannot mask a dangerous
    operation. Only an explicitly declared operation identity may authorise
    autonomous execution; anything else is treated as risky and therefore
    requires human approval.
    """
    text = normalise_operation_text(description)
    declared = {str(cap).strip().lower() for cap in (capabilities or [])}
    description_lower = text.lower()

    haystacks = (description_lower, *declared)
    for pattern in _DESTRUCTIVE_PATTERNS:
        for haystack in haystacks:
            if pattern.search(haystack):
                return TrustedRisk(
                    Risk.DESTRUCTIVE,
                    "classifier",
                    f"Matched a destructive operation pattern ({pattern.pattern})",
                    deny_level=True,
                )

    for pattern in _ADMIN_PATTERNS:
        for haystack in haystacks:
            if pattern.search(haystack):
                return TrustedRisk(
                    Risk.DESTRUCTIVE,
                    "classifier",
                    f"Matched a privileged administrative pattern ({pattern.pattern})",
                )

    for pattern in _RISKY_PATTERNS:
        for haystack in haystacks:
            if pattern.search(haystack):
                return TrustedRisk(
                    Risk.RISKY_WRITE,
                    "classifier",
                    f"Matched a human-approval operation pattern ({pattern.pattern})",
                )

    for candidate in sorted(declared | {description_lower}):
        if candidate in READ_OPERATION_IDS:
            return TrustedRisk(
                Risk.READ,
                "classifier",
                f"Matched declared read operation identity ({candidate})",
                declared_operation=True,
            )
        if candidate in SAFE_OPERATION_IDS:
            return TrustedRisk(
                Risk.SAFE_WRITE,
                "classifier",
                f"Matched declared safe operation identity ({candidate})",
                declared_operation=True,
            )

    return TrustedRisk(
        Risk.RISKY_WRITE,
        "classifier",
        "Operation identity is not declared by an operator allow-list",
    )
