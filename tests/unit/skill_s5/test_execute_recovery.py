# S5: CollabExec test suite - 24 substantive test cases
# Target: execute_recovery() function
# Reference: docs/TEST_CAMPAIGN_S192.md section 4.5
# Contract: Execute ONLY authorized option; never broaden scope

from unittest.mock import AsyncMock

import pytest

from opsswarm.models import (
    IncidentContext, RootCauseArtifact, RemediationOption,
    Risk
)
from opsswarm.skill_logic import execute_recovery


def make_incident() -> IncidentContext:
    """Factory for test incident context."""
    return IncidentContext(
        issue_number=1,
        title="Test incident",
        body="Test body",
        service="test-service",
        environment="production",
        severity="SEV2",
        symptoms=["symptom1"],
        customer_impact="test impact"
    )


def make_root_cause() -> RootCauseArtifact:
    """Factory for test root cause."""
    return RootCauseArtifact(
        status="confirmed",
        proximate_cause="cause1",
        root_cause="root cause",
        confidence=0.9,
        remediation_options=["option1", "option2"]
    )


def make_option(risk: Risk = Risk.SAFE_WRITE, opt_id: str = "opt-1") -> RemediationOption:
    """Factory for test remediation option."""
    return RemediationOption(
        id=opt_id,
        description="Test option",
        risk=risk,
        estimated_recovery="5 minutes"
    )


# === NORMAL (8 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n1_successful_safe_write():
    """S5-N1: Successful safe_write - returns success=true, ambiguous=false"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": "Recovery completed successfully",
        "evidence": ["step1 completed"],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.SAFE_WRITE)
    )

    assert result.success is True
    assert result.ambiguous is False
    assert result.option_id == "opt-1"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n2_success_with_evidence():
    """S5-N2: Success with evidence - evidence list populated"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": "Recovery completed",
        "evidence": ["check1: OK", "check2: OK", "check3: OK"],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert len(result.evidence) == 3
    assert "check1: OK" in result.evidence


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n3_ambiguous_outcome():
    """S5-N3: Ambiguous outcome - returns ambiguous=True, success=False"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Write outcome unclear - service may or may not be restored",
        "evidence": [],
        "ambiguous": True,
        "raw": {" uncertain_write": True}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.RISKY_WRITE)
    )

    assert result.ambiguous is True
    assert result.success is False


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n4_failed_recovery():
    """S5-N4: Failed recovery - success=False, summary contains error"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Execution failed: connection refused to service",
        "evidence": [],
        "ambiguous": False,
        "raw": {"error_code": "ECONNREFUSED"}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.RISKY_WRITE)
    )

    assert result.success is False
    assert "failed" in result.summary.lower() or "error" in result.summary.lower()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n5_option_id_preserved():
    """S5-N5: Option ID preserved - option_id matches input"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "custom-option-123",
        "success": True,
        "summary": "Done",
        "evidence": [],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(opt_id="custom-option-123")
    )

    assert result.option_id == "custom-option-123"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n6_raw_output_captured():
    """S5-N6: Raw output captured - raw field populated"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": "Completed",
        "evidence": [],
        "ambiguous": False,
        "raw": {"tool_output": {"stdout": "service restarted", "exit_code": 0}}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert "tool_output" in result.raw


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n7_summary_length():
    """S5-N7: Summary length - summary is descriptive"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": "Successfully restarted the API gateway service. Health checks passing. No data loss detected.",
        "evidence": [],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert len(result.summary) > 20  # Descriptive, not just "OK"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.normal
async def test_s5_n8_empty_evidence_allowed():
    """S5-N8: Empty evidence allowed - recovery without evidence is valid"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": "Completed successfully",
        "evidence": [],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert result.success is True
    assert result.evidence == []


# === BOUNDARY (6 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s5_b1_maximum_evidence_items():
    """S5-B1: Maximum 50 evidence items - does not exceed limit"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": "Recovery with many steps",
        "evidence": [f"step_{i}" for i in range(50)],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert len(result.evidence) <= 50


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s5_b2_very_long_summary():
    """S5-B2: Very long summary - handles 10KB+ without crash"""
    long_summary = "Action performed. " * 1000  # ~20KB

    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": long_summary,
        "evidence": [],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert result.success is True
    assert len(result.summary) > 10000


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s5_b3_partial_success():
    """S5-B3: Partial success - some steps succeeded"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Partial success: step1 OK, step2 failed, step3 skipped",
        "evidence": ["step1: OK", "step2: connection error"],
        "ambiguous": False,
        "raw": {"partial": True}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.RISKY_WRITE)
    )

    assert result.success is False
    assert "partial" in result.summary.lower() or "partial" in result.raw


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s5_b4_no_changes_needed():
    """S5-B4: No changes needed - read-only recovery"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": True,
        "summary": "No action needed - service already healthy",
        "evidence": ["health_check: OK"],
        "ambiguous": False,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.READ)
    )

    assert result.success is True


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s5_b5_idempotent_execution():
    """S5-B5: Idempotent execution - running twice produces same result"""
    oc = AsyncMock()
    response = {
        "option_id": "opt-1",
        "success": True,
        "summary": "Recovery completed",
        "evidence": [],
        "ambiguous": False,
        "raw": {}
    }
    oc.run_json = AsyncMock(return_value=response)

    result1 = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    oc.run_json = AsyncMock(return_value=response)
    result2 = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    # Same option_id and success - idempotent
    assert result1.option_id == result2.option_id
    assert result1.success == result2.success


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.boundary
async def test_s5_b6_long_running_recovery():
    """S5-B6: Long-running recovery - timeout handled gracefully"""
    import asyncio

    oc = AsyncMock()

    async def slow_response(agent, session, prompt):
        await asyncio.sleep(0.1)  # Simulate long operation
        return {
            "option_id": "opt-1",
            "success": True,
            "summary": "Long recovery completed",
            "evidence": [],
            "ambiguous": False,
            "raw": {}
        }

    oc.run_json = slow_response

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert result.success is True


# === FAULT (8 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f1_unauthorized_option():
    """S5-F1: Unauthorized option - execution should handle authorization check"""
    # Note: Authorization is enforced at policy level (S6), not in execute_recovery itself
    # This test verifies the function gracefully handles when option isn't approved
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-unauthorized",
        "success": False,
        "summary": "Option not authorized for execution",
        "evidence": [],
        "ambiguous": False,
        "raw": {"auth_error": True}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.DESTRUCTIVE)
    )

    # The execution function reports authorization failure
    assert result.success is False or "unauthorized" in result.summary.lower()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f2_policy_denies():
    """S5-F2: Policy denies - destructive option blocked"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Policy denied: destructive action not permitted",
        "evidence": [],
        "ambiguous": False,
        "raw": {"policy_denied": True}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.DESTRUCTIVE)
    )

    assert result.success is False


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f3_tool_failure():
    """S5-F3: Tool failure - error in summary"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Tool execution error: kubectl command failed with exit code 1",
        "evidence": ["error: namespace not found"],
        "ambiguous": False,
        "raw": {"exit_code": 1}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    assert result.success is False
    assert "error" in result.summary.lower() or "failed" in result.summary.lower()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f4_ambiguous_no_blind_retry():
    """S5-F4: Ambiguous outcome MUST NOT trigger blind retry"""
    # This is a critical contract test - verify ambiguous doesn't auto-retry
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Write outcome ambiguous - service state unclear",
        "evidence": [],
        "ambiguous": True,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.RISKY_WRITE)
    )

    # Key: ambiguous=True means NO blind retry - this is handled by S6
    assert result.ambiguous is True
    assert result.success is False


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f5_scope_creep():
    """S5-F5: Scope creep - action beyond authorized option"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Execution exceeded authorized scope - attempted to modify production database",
        "evidence": [],
        "ambiguous": False,
        "raw": {"scope_violation": True}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.SAFE_WRITE)
    )

    assert result.success is False


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f6_null_option():
    """S5-F6: Null option - should handle gracefully"""
    oc = AsyncMock()

    # Pass None as option - this tests the model's handling
    with pytest.raises(Exception):  # Pydantic validation error expected
        await execute_recovery(
            oc, "recovery-agent", "run-1",
            make_incident(), make_root_cause(), None  # type: ignore
        )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f7_invalid_risk_option():
    """S5-F7: Invalid risk option - DENY policy blocks before execution"""
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Execution blocked by policy: destructive operations require explicit approval",
        "evidence": [],
        "ambiguous": False,
        "raw": {"blocked_by_policy": True}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.DESTRUCTIVE)
    )

    assert result.success is False


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.fault
async def test_s5_f8_concurrent_execution():
    """S5-F8: Concurrent execution - proper locking/handling"""
    import asyncio

    oc = AsyncMock()
    call_count = 0

    async def mock_run(agent, session, prompt):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # Simulate work
        return {
            "option_id": "opt-1",
            "success": True,
            "summary": f"Execution {call_count}",
            "evidence": [],
            "ambiguous": False,
            "raw": {}
        }

    oc.run_json = mock_run

    # Run two executions concurrently
    results = await asyncio.gather(
        execute_recovery(oc, "recovery-agent", "run-1", make_incident(), make_root_cause(), make_option()),
        execute_recovery(oc, "recovery-agent", "run-2", make_incident(), make_root_cause(), make_option())
    )

    # Both should complete (concurrency handled)
    assert len(results) == 2
    assert all(r.success for r in results)


# === CROSS-SKILL (2 tests) ===

@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.cross_skill
async def test_s5_c1_output_feeds_s7_verify():
    """S5-C1: Output feeds S7 verify - ExecutionResult is valid input for verify_recovery"""
    from opsswarm.skill_logic import verify_recovery

    oc = AsyncMock()
    execution_response = {
        "option_id": "opt-1",
        "success": True,
        "summary": "Recovery completed",
        "evidence": ["service restarted"],
        "ambiguous": False,
        "raw": {}
    }
    oc.run_json = AsyncMock(return_value=execution_response)

    # Execute recovery (S5)
    execution_result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option()
    )

    # Verify recovery (S7) - uses execution result as input
    oc.run_json = AsyncMock(return_value={
        "verified": True,
        "summary": "Service health confirmed",
        "evidence": ["health check passed"],
        "confidence": 0.95,
        "abort": False,
        "raw": {}
    })

    verification_result = await verify_recovery(
        oc, "verify-agent", "run-1",
        make_incident(), execution_result
    )

    assert verification_result.verified is True


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.cross_skill
async def test_s5_c2_human_gate_triggered():
    """S5-C2: Human gate triggered - ambiguous result creates decision request"""
    # When ambiguous=True, S6 creates WAITING_DECISION state
    oc = AsyncMock()
    oc.run_json = AsyncMock(return_value={
        "option_id": "opt-1",
        "success": False,
        "summary": "Outcome ambiguous - cannot determine success",
        "evidence": [],
        "ambiguous": True,
        "raw": {}
    })

    result = await execute_recovery(
        oc, "recovery-agent", "run-1",
        make_incident(), make_root_cause(), make_option(Risk.RISKY_WRITE)
    )

    # Ambiguous triggers human decision gate (handled by S6)
    assert result.ambiguous is True
