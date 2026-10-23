from opsswarm.models import Finding, RootCauseArtifact, RecoveryPlan
from opsswarm.normalization import (
    normalize_finding,
    normalize_root_cause_artifact,
    normalize_recovery_plan,
    normalize_list_of_strings,
)


def test_finding_normalization_evidence_dict():
    # Reproduction: evidence as a dict
    invalid_data = {
        "task_id": "t1",
        "finding": "something happened",
        "evidence": {"type": "file", "path": "/tmp/a.txt"},
        "confidence": 0.9,
    }

    normalized_data = normalize_finding(invalid_data)
    # Should validate
    Finding.model_validate(normalized_data)


def test_finding_normalization_confidence_str():
    # Reproduction: confidence as a str
    invalid_data = {
        "task_id": "t1",
        "finding": "something happened",
        "evidence": ["/tmp/a.txt"],
        "confidence": "high",
    }

    normalized_data = normalize_finding(invalid_data)
    # Should validate
    Finding.model_validate(normalized_data)


def test_root_cause_normalization():
    invalid_data = {
        "evidence_refs": {"type": "link", "ref": "http://x"},
        "remediation_options": {"id": "1", "desc": "do this"},
        # Note: Field is remediation_options in RootCauseArtifact which is list[str]
        "corrective_actions": {"action": "fix it"},
        "confidence": "low",
        "human_input_question": {"question": "really?"},
    }

    normalized_data = normalize_root_cause_artifact(invalid_data)
    # Should validate
    RootCauseArtifact.model_validate(normalized_data)


def test_recovery_plan_normalization():
    invalid_data = {
        "options": [
            {"id": "1", "description": "do it", "risk": "read", "capabilities": {"cap1": "yes"}}
        ],
        "confidence": "medium",
        "business_input_question": {"q": "yes?"},
    }

    normalized_data = normalize_recovery_plan(invalid_data)
    # Should validate
    RecoveryPlan.model_validate(normalized_data)


def test_dict_evidence_pii_redacted():
    """Regression for r4111809810: dict evidence values must have PII redacted.

    Previously the dict branch in normalize_list_of_strings just formatted
    f"{k}: {v}" without calling redact_pii(), leaving emails intact.
    """
    pii_dict = {"actor": "alice@corp.example.com", "action": "deploy"}
    result = normalize_list_of_strings(pii_dict)
    # Each entry must be a string with email redacted
    joined = " ".join(result)
    assert "alice@corp.example.com" not in joined, (
        f"Email must be redacted in dict evidence, got: {result}"
    )
    assert "[REDACTED]" in joined


def test_nested_dict_in_list_pii_redacted():
    """A list containing dict items must also have PII redacted when stringified."""
    data = [{"actor": "bob@evil.example.com"}, "plain string with no@email.com"]
    result = normalize_list_of_strings(data)
    joined = " ".join(result)
    # redact_pii is applied via str(x) on each list item already, but confirm:
    assert "bob@evil.example.com" not in joined
    assert "no@email.com" not in joined


# --- C-07: normalize_optional_string PII redaction ---

from opsswarm.normalization import normalize_optional_string


def test_optional_string_email_in_plain_str_redacted():
    """Email in a plain string value is redacted."""
    result = normalize_optional_string("Contact user@example.com immediately")
    assert "[REDACTED]" in result
    assert "user@example.com" not in result


def test_optional_string_email_in_dict_redacted():
    """Email buried in a dict value is redacted when stringified."""
    result = normalize_optional_string({"text": "Contact user@example.com immediately"})
    assert "[REDACTED]" in result
    assert "user@example.com" not in result


def test_optional_string_none_returns_none():
    """None input returns None, no crash."""
    assert normalize_optional_string(None) is None


def test_optional_string_no_pii_plain_passthrough():
    """Plain string with no PII returns unchanged."""
    result = normalize_optional_string("No PII here")
    assert result == "No PII here"


def test_optional_string_dict_no_pii_stringified():
    """Dict with no PII returns stringified representation."""
    result = normalize_optional_string({"key": "value"})
    assert result == "{'key': 'value'}"


def test_optional_string_int_coerced_and_redacted():
    """Non-string/dict types are coerced via str() and redacted."""
    assert normalize_optional_string(42) == "42"


def test_root_cause_human_input_question_email_redacted():
    """C-07: Email in human_input_question is redacted."""
    data = {
        "status": "uncertain",
        "proximate_cause": "service crash",
        "root_cause": "unknown",
        "human_input_question": "Did alice@example.com trigger this incident?",
    }
    normalized = normalize_root_cause_artifact(data)
    assert "[REDACTED]" in normalized["human_input_question"]
    assert "alice@example.com" not in normalized["human_input_question"]


def test_root_cause_human_input_question_dict_email_redacted():
    """C-07: Email inside a dict-valued human_input_question is redacted."""
    data = {
        "status": "uncertain",
        "proximate_cause": "service crash",
        "root_cause": "unknown",
        "human_input_question": {"question": "Contact bob@corp.example for context"},
    }
    normalized = normalize_root_cause_artifact(data)
    assert "[REDACTED]" in normalized["human_input_question"]
    assert "bob@corp.example" not in normalized["human_input_question"]


def test_recovery_plan_business_input_question_email_redacted():
    """C-07: Email in business_input_question is redacted."""
    data = {
        "options": [],
        "business_input_question": "Was this triggered by ops@example.com?",
    }
    normalized = normalize_recovery_plan(data)
    assert "[REDACTED]" in normalized["business_input_question"]
    assert "ops@example.com" not in normalized["business_input_question"]


def test_recovery_plan_business_input_question_dict_email_redacted():
    """C-07: Email inside a dict-valued business_input_question is redacted."""
    data = {
        "options": [],
        "business_input_question": {"q": "Contact noc@company.org for approval"},
    }
    normalized = normalize_recovery_plan(data)
    assert "[REDACTED]" in normalized["business_input_question"]
    assert "noc@company.org" not in normalized["business_input_question"]
