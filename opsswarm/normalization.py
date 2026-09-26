from __future__ import annotations
import re
from typing import Any

def redact_pii(text: str) -> str:
    """Redact simple PII like emails."""
    return re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED]', text)


def normalize_confidence(value: Any) -> float:
    """Normalize confidence to float, handling string variants."""
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        mapping = {"high": 0.9, "medium": 0.5, "low": 0.1}
        return mapping.get(value.lower(), 0.0)
    return 0.0


def normalize_list_of_strings(value: Any) -> list[str]:
    """Normalize input to list of strings, handling dictionaries, strings, and lists."""
    if isinstance(value, list):
        return [redact_pii(str(x)) for x in value]
    if isinstance(value, str):
        return [redact_pii(value)]
    if isinstance(value, dict):
        # Flatten dictionary if it's structured evidence
        return [f"{k}: {v}" for k, v in value.items()]
    return []


def normalize_optional_string(value: Any) -> str | None:
    """Normalize input to optional string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value)
    return str(value)


def normalize_finding(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize Finding data."""
    normalized = data.copy()
    if "evidence" in normalized:
        normalized["evidence"] = normalize_list_of_strings(normalized["evidence"])
    if "confidence" in normalized:
        normalized["confidence"] = normalize_confidence(normalized["confidence"])
    return normalized


def normalize_root_cause_artifact(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize RootCauseArtifact data."""
    normalized = data.copy()
    if "evidence_refs" in normalized:
        normalized["evidence_refs"] = normalize_list_of_strings(normalized["evidence_refs"])
    if "remediation_options" in normalized:
        normalized["remediation_options"] = normalize_list_of_strings(normalized["remediation_options"])
    if "corrective_actions" in normalized:
        normalized["corrective_actions"] = normalize_list_of_strings(normalized["corrective_actions"])
    if "confidence" in normalized:
        normalized["confidence"] = normalize_confidence(normalized["confidence"])
    if "human_input_question" in normalized:
        normalized["human_input_question"] = normalize_optional_string(normalized["human_input_question"])
    return normalized


def normalize_remidiation_option(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize RemediationOption data."""
    normalized = data.copy()
    if "risk" in normalized:
        # risk needs to be a Risk enum, string is fine if it matches
        pass
    if "capabilities" in normalized:
        normalized["capabilities"] = normalize_list_of_strings(normalized["capabilities"])
    return normalized


def normalize_recovery_plan(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize RecoveryPlan data."""
    normalized = data.copy()
    if "options" in normalized and isinstance(normalized["options"], list):
        normalized["options"] = [normalize_remidiation_option(opt) if isinstance(opt, dict) else opt for opt in
                                 normalized["options"]]
    if "confidence" in normalized:
        normalized["confidence"] = normalize_confidence(normalized["confidence"])
    if "business_input_question" in normalized:
        normalized["business_input_question"] = normalize_optional_string(normalized["business_input_question"])
    return normalized
