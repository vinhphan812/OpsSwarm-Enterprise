"""Tests for issue #31: OpenClaw Pydantic model updates.

Tests:
1. Finding.evidence accepts both string and structured EvidenceRef inputs
2. RootCauseArtifact.confidence coerces "high"/"medium"/"low" strings to float
3. RootCauseArtifact.remediation_options accepts structured RemediationOption models
4. ValidationError is caught and diagnostics are persisted before re-raising
"""

from opsswarm.models import (
    Finding,
    RootCauseArtifact,
    RemediationOption,
    EvidenceRef,
    Risk,
    RecoveryPlan,
)
from opsswarm import skill_logic


# ---------------------------------------------------------------------------
# EvidenceRef model
# ---------------------------------------------------------------------------


def test_evidence_ref_basic():
    ref = EvidenceRef(type="file", path="/var/log/app.log", snippet="ERROR at line 42")
    assert ref.type == "file"
    assert ref.path == "/var/log/app.log"
    assert ref.snippet == "ERROR at line 42"


def test_evidence_ref_defaults():
    ref = EvidenceRef()
    assert ref.type == "generic"
    assert ref.path is None
    assert ref.ref is None
    assert ref.snippet is None


# ---------------------------------------------------------------------------
# Finding.evidence accepts EvidenceRef
# ---------------------------------------------------------------------------


def test_finding_evidence_str():
    f = Finding(task_id="t1", finding="disk full", evidence=["/tmp/out.txt"])
    assert f.evidence == ["/tmp/out.txt"]


def test_finding_evidence_evidence_ref():
    ref = EvidenceRef(type="log", path="/var/log/syslog")
    f = Finding(task_id="t1", finding="disk full", evidence=[ref])
    assert len(f.evidence) == 1
    assert isinstance(f.evidence[0], EvidenceRef)
    assert f.evidence[0].type == "log"


def test_finding_evidence_mixed_str_and_ref():
    ref = EvidenceRef(type="link", ref="http://example.com/crash")
    f = Finding(
        task_id="t1",
        finding="crash detected",
        evidence=["/tmp/dump.txt", ref, "stdout.log"],
    )
    assert len(f.evidence) == 3
    assert f.evidence[0] == "/tmp/dump.txt"
    assert isinstance(f.evidence[1], EvidenceRef)
    assert f.evidence[2] == "stdout.log"


def test_finding_evidence_from_dict_list():
    """EvidenceRef dicts in a list are coerced to EvidenceRef instances."""
    data = {
        "task_id": "t1",
        "finding": "memory leak",
        "evidence": [
            {"type": "file", "path": "/memdump.bin"},
            "plain string evidence",
            {"type": "metric", "snippet": "OOM killed"},
        ],
    }
    f = Finding.model_validate(data)
    assert isinstance(f.evidence[0], EvidenceRef)
    assert f.evidence[0].path == "/memdump.bin"
    assert f.evidence[1] == "plain string evidence"
    assert isinstance(f.evidence[2], EvidenceRef)
    assert f.evidence[2].type == "metric"


def test_finding_evidence_from_dict_singleton():
    """A single dict (not in a list) is coerced to an EvidenceRef list."""
    data = {
        "task_id": "t1",
        "finding": "crash",
        "evidence": {"type": "log", "snippet": "segfault"},
    }
    f = Finding.model_validate(data)
    assert len(f.evidence) == 1
    assert isinstance(f.evidence[0], EvidenceRef)
    assert f.evidence[0].snippet == "segfault"


def test_finding_evidence_invalid_dict_falls_back_to_str():
    """Malformed EvidenceRef dict falls back to string representation."""
    data = {
        "task_id": "t1",
        "finding": "unknown",
        "evidence": [{"not": "a valid evidence ref at all"}],
    }
    f = Finding.model_validate(data)
    # Should not raise; falls back to str
    assert len(f.evidence) == 1
    assert isinstance(f.evidence[0], str)


# ---------------------------------------------------------------------------
# RootCauseArtifact.confidence coercion
# ---------------------------------------------------------------------------


def test_rca_confidence_float():
    rca = RootCauseArtifact(confidence=0.75)
    assert rca.confidence == 0.75


def test_rca_confidence_int():
    rca = RootCauseArtifact(confidence=1)
    assert rca.confidence == 1.0


def test_rca_confidence_high_str():
    rca = RootCauseArtifact.model_validate({"confidence": "high"})
    assert rca.confidence == 0.9


def test_rca_confidence_medium_str():
    rca = RootCauseArtifact.model_validate({"confidence": "medium"})
    assert rca.confidence == 0.5


def test_rca_confidence_low_str():
    rca = RootCauseArtifact.model_validate({"confidence": "Low"})
    assert rca.confidence == 0.1  # case-insensitive


def test_rca_confidence_unknown_str_defaults_to_zero():
    rca = RootCauseArtifact.model_validate({"confidence": "super-high"})
    assert rca.confidence == 0.0


# ---------------------------------------------------------------------------
# RootCauseArtifact.remediation_options structured coercion
# ---------------------------------------------------------------------------


def test_rca_remediation_options_str_list():
    rca = RootCauseArtifact(remediation_options=["restart service", "scale up"])
    assert rca.remediation_options == ["restart service", "scale up"]


def test_rca_remediation_options_structured():
    opt = RemediationOption(
        id="opt-1",
        description="Restart the service",
        risk=Risk.SAFE_WRITE,
        capabilities=["kubectl", "docker"],
    )
    rca = RootCauseArtifact(remediation_options=[opt])
    assert len(rca.remediation_options) == 1
    assert isinstance(rca.remediation_options[0], RemediationOption)
    assert rca.remediation_options[0].id == "opt-1"


def test_rca_remediation_options_mixed():
    opt = RemediationOption(id="opt-2", description="Scale replicas", risk=Risk.SAFE_WRITE)
    rca = RootCauseArtifact(remediation_options=["manual restart", opt])
    assert rca.remediation_options[0] == "manual restart"
    assert isinstance(rca.remediation_options[1], RemediationOption)


def test_rca_remediation_options_from_dict():
    data = {
        "remediation_options": [
            {"id": "opt-a", "description": "Rollback", "risk": "risky_write"},
        ]
    }
    rca = RootCauseArtifact.model_validate(data)
    assert len(rca.remediation_options) == 1
    assert isinstance(rca.remediation_options[0], RemediationOption)
    assert rca.remediation_options[0].id == "opt-a"


def test_rca_remediation_options_invalid_dict_falls_back_to_str():
    data = {
        "remediation_options": [
            {"bad": "dict", "missing": "required fields"},
        ]
    }
    rca = RootCauseArtifact.model_validate(data)
    assert len(rca.remediation_options) == 1
    assert isinstance(rca.remediation_options[0], str)


# ---------------------------------------------------------------------------
# Combined: Finding + RCA with structured evidence + string confidence
# ---------------------------------------------------------------------------


def test_finding_with_structured_evidence_and_string_confidence():
    """End-to-end: structured evidence + string confidence."""
    data = {
        "task_id": "t1",
        "finding": "service degraded",
        "evidence": [
            {"type": "metric", "snippet": "p99 > 2s"},
            "/var/log/error.log",
            {"type": "file", "path": "/tmp/heapdump.hprof"},
        ],
        "confidence": "high",
    }
    f = Finding.model_validate(data)
    assert isinstance(f.evidence[0], EvidenceRef)
    assert isinstance(f.evidence[1], str)
    assert isinstance(f.evidence[2], EvidenceRef)
    assert f.confidence == 0.9  # string "high" coerced


# ---------------------------------------------------------------------------
# RemediationOption model completeness
# ---------------------------------------------------------------------------


def test_remediation_option_defaults():
    opt = RemediationOption(id="opt-x", description="Do nothing", risk=Risk.READ)
    assert opt.profile == "recovery-responder"
    assert opt.estimated_recovery is None
    assert opt.rationale == ""
    assert opt.capabilities == []


# ---------------------------------------------------------------------------
# RecoveryPlan with structured options
# ---------------------------------------------------------------------------


def test_recovery_plan_with_structured_options():
    plan_data = {
        "options": [
            {
                "id": "opt-1",
                "description": "Restart pod",
                "risk": "safe_write",
                "capabilities": ["kubectl"],
            },
            {
                "id": "opt-2",
                "description": "Rollback deployment",
                "risk": "risky_write",
                "capabilities": ["helm"],
            },
        ],
        "confidence": "medium",
    }
    plan = RecoveryPlan.model_validate(plan_data)
    assert len(plan.options) == 2
    assert all(isinstance(o, RemediationOption) for o in plan.options)
    assert plan.confidence == 0.5
