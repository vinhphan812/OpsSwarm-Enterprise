from opsswarm.models import Finding, RootCauseArtifact, RecoveryPlan
from opsswarm.normalization import normalize_finding, normalize_root_cause_artifact, normalize_recovery_plan


def test_finding_normalization_evidence_dict():
    # Reproduction: evidence as a dict
    invalid_data = {
        "task_id": "t1",
        "finding": "something happened",
        "evidence": {"type": "file", "path": "/tmp/a.txt"},
        "confidence": 0.9
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
        "confidence": "high"
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
        "human_input_question": {"question": "really?"}
    }

    normalized_data = normalize_root_cause_artifact(invalid_data)
    # Should validate
    RootCauseArtifact.model_validate(normalized_data)


def test_recovery_plan_normalization():
    invalid_data = {
        "options": [{"id": "1", "description": "do it", "risk": "read", "capabilities": {"cap1": "yes"}}],
        "confidence": "medium",
        "business_input_question": {"q": "yes?"}
    }

    normalized_data = normalize_recovery_plan(invalid_data)
    # Should validate
    RecoveryPlan.model_validate(normalized_data)
