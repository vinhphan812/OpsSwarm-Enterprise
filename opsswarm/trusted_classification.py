"""Operator-owned risk classification for autonomous remediation (ADR-013 D3).

The risk label produced by the model is never an authorisation. It may only
*raise* the effective risk of a remediation option; it can never lower it.

The effective risk of a remediation option is decided by operator-owned
sources only:

  1. the capability registry (``config/capability-registry.yaml``) — an
     operator-maintained allow-list/block-list;
  2. this module — a deterministic classifier over the operation description.

Free-text descriptions never authorise execution on their own: a description
that matches no operator-declared operation is *unknown* and is routed to a
human approval gate.

Trust boundary (ADR-013 D3, amended by Issue #134 / PR #133)
--------------------------------------------------
Only two inputs may authorise autonomous execution, and neither of them is a
model-supplied *claim*:

  * an operation-registry rule matched against the operation text;
  * the operation **description** being exactly an operator-declared operation
    identity (a controlled vocabulary term).

``RemediationOption.capabilities`` is model-authored: the S3 model emits it in
the recovery-plan JSON and no operator validates its membership. It is
therefore never used as an authorisation input. It may only *raise* risk: a
capability that names a destructive or otherwise risky operation is escalated.
A capability list that claims an operation identity the description does not
carry cannot make the option safe.

A description may chain several commands. Each chained command is a separate
segment and is resolved on its own, so an allow-listed command cannot
authorise a destructive command chained behind it.

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
    "known_operation_ids",
    "normalise_operation_text",
    "split_operation_segments",
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
        r"\bremove\s+all\s+(\w+\s+)?data\b",
        r"\bterminate\b[^;|]*\bcluster\b",
    )
)


# Privileged administrative mutations. The capability registry classifies
# these as human-approval operations (ADR-013), so a registry match may
# override this classification; without a registry match they are treated as
# destructive.
_ADMIN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (r"\bpatch\s+/admin/",)
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


def known_operation_ids() -> frozenset[str]:
    """Return every operator-declared operation identity."""
    return SAFE_OPERATION_IDS | READ_OPERATION_IDS


def split_operation_segments(description: str | None) -> list[str]:
    """Split an operation description into individually executable segments.

    A description may chain several commands (``;``, ``&&``, ``||``, ``|``, a
    newline, a command substitution or a backtick). Each segment is resolved
    on its own, so an allow-listed command cannot authorise a destructive
    command chained behind it.

    Separators inside single or double quotes are ignored, so a quoted
    argument is never torn apart.
    """
    text = normalise_operation_text(description)
    if not text:
        return []

    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    substitution_depth = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue
        remainder = text[index:]
        if remainder.startswith("&&") or remainder.startswith("||"):
            segments.append("".join(current))
            current = []
            index += 2
            continue
        if char in {";", "|", "\n", "`"}:
            segments.append("".join(current))
            current = []
            index += 1
            continue
        if remainder.startswith("$("):
            # A command substitution starts a new, separately evaluated command.
            segments.append("".join(current))
            current = []
            substitution_depth = 1
            index += 2
            continue
        if substitution_depth and char == "(":
            substitution_depth += 1
            current.append(char)
            index += 1
            continue
        if substitution_depth and char == ")":
            substitution_depth -= 1
            if substitution_depth == 0:
                # The substitution closes here; the command inside is the segment.
                segments.append("".join(current))
                current = []
                index += 1
                continue
            current.append(char)
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))

    return [segment.strip() for segment in segments if segment.strip()]


def classify_trusted_operation(
    description: str | None,
    capabilities: Sequence[str] | None = None,
) -> TrustedRisk:
    """Classify a remediation option using operator-owned rules only.

    Destructive and risky markers are inspected across both the description
    and the declared capabilities, so a benign verb cannot mask a dangerous
    operation. Model-supplied capabilities may only *raise* the risk; they
    never authorise execution. Only a description that is exactly an
    operator-declared operation identity authorises a safe or read operation;
    anything else is treated as risky and therefore requires human approval.
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

    # The description is the operation that is actually performed, so it is
    # the only model-supplied field that may carry a declared operation
    # identity. The match is exact: the whole description must be the
    # operator-declared identity. A capability list cannot stand in for it.
    if description_lower in READ_OPERATION_IDS:
        return TrustedRisk(
            Risk.READ,
            "classifier",
            f"Matched declared read operation identity ({description_lower})",
            declared_operation=True,
        )
    if description_lower in SAFE_OPERATION_IDS:
        return TrustedRisk(
            Risk.SAFE_WRITE,
            "classifier",
            f"Matched declared safe operation identity ({description_lower})",
            declared_operation=True,
        )

    return TrustedRisk(
        Risk.RISKY_WRITE,
        "classifier",
        "Operation identity is not declared by an operator allow-list",
    )
