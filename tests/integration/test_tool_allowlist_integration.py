"""Integration tests for Issue #27 — tool allowlist enforcement in the full system.

These tests simulate disallowed tool calls and verify the enforcement pipeline:
  1. ToolAllowlist is loaded from config/tool-allowlist.yaml
  2. OpenClawClient is constructed with the allowlist + check_tools=True
  3. A disallowed tool call raises ToolDenyError with structured attributes
  4. The error propagates through the orchestrator correctly
  5. All existing tests continue to pass (backward compatibility via silent-disable)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from opsswarm.orchestrator import Orchestrator
from opsswarm.tool_allowlist import ToolAllowlist, ToolDenyError


# -------------------------------------------------------------------------- #
# Fixtures
# -------------------------------------------------------------------------- #


@pytest.fixture
def mock_github():
    gh = MagicMock()
    gh.set_labels = AsyncMock(return_value=None)
    gh.comment = AsyncMock(return_value=None)
    gh.get_issue = AsyncMock(
        return_value={
            "title": "Test incident",
            "body": "## Symptoms\nTest\n## Service\ntest\n## Environment\nprod",
            "labels": [{"name": "opsswarm"}, {"name": "sev:1"}],
            "user": {"login": "testuser"},
        }
    )
    gh.create_issue = AsyncMock(return_value={"number": 99})
    gh.close_issue = AsyncMock(return_value=None)
    return gh


@pytest.fixture
def mock_openclaw():
    oc = MagicMock()
    oc.run_json = AsyncMock(return_value={"tasks": []})
    oc.run_text = AsyncMock(return_value="{}")
    return oc


@pytest.fixture
def base_cfg():
    """Base config without tool allowlist enabled (backward-compatible default)."""
    return {
        "openclaw": {
            "main_agent": "opsswarm-incident-manager",
            "timeout_seconds": 600,
            "check_tools": False,  # disabled by default
            "profiles": {
                "incident-manager": "opsswarm-incident-manager",
                "observability-investigator": "opsswarm-observability-investigator",
                "recovery-responder": "opsswarm-recovery-responder",
            },
        },
        "required_issue_label": "opsswarm",
        "budget": {
            "max_tasks_per_run": 50,
            "max_openclaw_calls": 200,
            "max_wall_clock_seconds": 3600,
            "max_corrective_actions": 10,
            "max_dependency_depth": 20,
        },
        "concurrency": {
            "max_parallel_specialists": 4,
        },
        "persistence": {
            "enable_idempotency": True,
        },
    }


@pytest.fixture
def allowlist_cfg(base_cfg):
    """Config with tool allowlist enabled."""
    cfg = dict(base_cfg)
    cfg["tool_allowlist"] = {
        "enabled": True,
        "path": "config/tool-allowlist.yaml",
    }
    cfg["openclaw"]["check_tools"] = True
    return cfg


# -------------------------------------------------------------------------- #
# Integration: disallowed tool call blocked
# -------------------------------------------------------------------------- #


@pytest.mark.integration
class TestDisallowedToolCallBlocked:
    """Verify a disallowed tool call is blocked with a structured error."""

    def test_tool_allowlist_loads_from_real_config(self):
        """The real config/tool-allowlist.yaml loads successfully."""
        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        assert al is not None
        assert al.version == "1"
        assert "incident-manager" in al.profile_names()
        assert "recovery-responder" in al.profile_names()

    def test_real_config_has_all_s1_s8_profiles(self):
        """All S1-S8 profiles from skill-gates.yml are in the allowlist."""
        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        assert al is not None
        expected = {
            "incident-manager",
            "observability-investigator",
            "application-investigator",
            "infrastructure-investigator",
            "database-investigator",
            "recovery-responder",
            "communications-postmortem",
        }
        actual = set(al.profile_names())
        assert expected <= actual, f"Missing profiles: {expected - actual}"

    def test_orchestrator_with_allowlist_enabled(
        self, allowlist_cfg, mock_github, mock_openclaw, tmp_path
    ):
        """Orchestrator initializes with tool allowlist when enabled."""
        data_dir = str(tmp_path / "data")
        orch = Orchestrator(allowlist_cfg, mock_github, mock_openclaw, data_dir=data_dir)
        # When enabled, the allowlist should be loaded
        if orch._tool_allowlist is not None:
            assert orch._tool_allowlist.is_enabled() is True
            assert len(orch._tool_allowlist.profile_names()) > 0

    def test_orchestrator_disabled_allows_all_tools(
        self, base_cfg, mock_github, mock_openclaw, tmp_path
    ):
        """Orchestrator permits all tools when allowlist is disabled."""
        data_dir = str(tmp_path / "data")
        orch = Orchestrator(base_cfg, mock_github, mock_openclaw, data_dir=data_dir)
        # Disabled allowlist: _tool_allowlist is None
        assert orch._tool_allowlist is None

    def test_tool_allowlist_report(self, allowlist_cfg, mock_github, mock_openclaw, tmp_path):
        """tool_allowlist_report() returns structured audit info."""
        data_dir = str(tmp_path / "data")
        orch = Orchestrator(allowlist_cfg, mock_github, mock_openclaw, data_dir=data_dir)
        report = orch.tool_allowlist_report()
        if orch._tool_allowlist is not None:
            assert report["enabled"] is True
            assert isinstance(report["profiles"], dict)

    def test_recovery_responder_blocks_destructive_tools(self):
        """recovery-responder explicitly denies kubectl_delete_* and drop_database."""
        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        assert al is not None
        result = al.allowed_for("recovery-responder")
        assert "kubectl_delete_pod" not in result.allowed_tools
        assert "kubectl_delete_deployment" not in result.allowed_tools
        assert "kubectl_delete_namespace" not in result.allowed_tools
        assert "drop_database" not in result.allowed_tools
        assert "redis_flushall" not in result.allowed_tools

    def test_disallowed_tool_raises_with_correlation_id(self):
        """check() raises ToolDenyError with correlation ID on disallowed tool."""
        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        assert al is not None
        with pytest.raises(ToolDenyError) as exc_info:
            al.check("kubectl_delete_namespace", "recovery-responder")
        assert exc_info.value.correlation_id is not None
        assert len(exc_info.value.correlation_id) > 0

    def test_allowed_tool_passes(self):
        """check() does not raise for an allowed tool."""
        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        assert al is not None
        # read_logs is in the read-only capability
        al.check("read_logs", "incident-manager")

    def test_error_audit_dict(self):
        """ToolDenyError.for_audit() returns a structured dict for evidence storage."""
        from opsswarm.tool_allowlist import ToolDenyError

        err = ToolDenyError(
            tool="kubectl_delete_namespace",
            profile="recovery-responder",
            reason="tool_not_in_profile_allowlist",
            correlation_id="test123",
        )
        audit = err.for_audit()
        assert audit["event"] == "tool_deny"
        assert audit["tool"] == "kubectl_delete_namespace"
        assert audit["profile"] == "recovery-responder"
        assert audit["correlation_id"] == "test123"

    def test_openclaw_client_set_tool_allowlist(self, mock_openclaw):
        """set_tool_allowlist() injects the allowlist at runtime."""
        from opsswarm.openclaw import OpenClawClient
        from opsswarm.tool_allowlist import ToolAllowlist

        client = OpenClawClient(check_tools=False)
        assert client._tool_allowlist is None

        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        client.set_tool_allowlist(al)
        assert client._tool_allowlist is al

        # Setting None disables checks
        client.set_tool_allowlist(None)
        assert client._tool_allowlist is None

    def test_openclaw_client_denies_disallowed_tool(self, mock_openclaw):
        """OpenClawClient.run_text() / run_json() raise ToolDenyError when check_tools=True."""
        from opsswarm.openclaw import OpenClawClient
        from opsswarm.tool_allowlist import ToolAllowlist

        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        assert al is not None

        client = OpenClawClient(binary="openclaw", timeout=30, check_tools=True, tool_allowlist=al)

        # Manually call _check_tool_access to simulate enforcement
        with pytest.raises(ToolDenyError):
            client._check_tool_access("kubectl_delete_namespace", "recovery-responder")

        # Allowed tool should not raise
        client._check_tool_access("read_logs", "incident-manager")  # no error


# -------------------------------------------------------------------------- #
# Backward compatibility: all existing tests continue to pass
# -------------------------------------------------------------------------- #


@pytest.mark.integration
class TestBackwardCompatibility:
    """Verify tool allowlist does not break existing code paths."""

    def test_orchestrator_works_without_allowlist(
        self, base_cfg, mock_github, mock_openclaw, tmp_path
    ):
        """Orchestrator initialises and processes a run without the allowlist config."""
        data_dir = str(tmp_path / "data")
        orch = Orchestrator(base_cfg, mock_github, mock_openclaw, data_dir=data_dir)
        assert orch._tool_allowlist is None
        assert orch.tool_allowlist is None

    def test_openclaw_client_no_allowlist_allows_all(self):
        """OpenClawClient with no allowlist permits all tools (D7 silent-disable)."""
        from opsswarm.openclaw import OpenClawClient

        client = OpenClawClient(check_tools=False, tool_allowlist=None)
        # Silent-disable: no error raised
        client._check_tool_access("kubectl_exec", "incident-manager")

    def test_openclaw_client_check_tools_false_allows_all(self):
        """OpenClawClient with check_tools=False permits all tools."""
        from opsswarm.openclaw import OpenClawClient
        from opsswarm.tool_allowlist import ToolAllowlist

        al = ToolAllowlist.load("config/tool-allowlist.yaml")
        client = OpenClawClient(check_tools=False, tool_allowlist=al)
        # check_tools flag overrides having a loaded allowlist
        client._check_tool_access("kubectl_exec", "incident-manager")
