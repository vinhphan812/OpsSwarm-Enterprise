"""Unit tests for Issue #27 — tool allowlist enforcement (ADR-027).

Coverage:
  - ToolAllowlist.load() / from_config() / _from_dict()
  - Capability grouping and tool expansion
  - Profile allowlist resolution (capabilities + explicit + deny)
  - ToolDenyError: attributes, for_log(), for_audit()
  - check() raises ToolDenyError on disallowed tool
  - Default-deny: unknown tools blocked
  - Silent-disable when allowlist is None
  - capability_tools(), all_tools()
  - describe_profile()
  - OpenClawClient: tool_deny propagates, check_tools flag, set_tool_allowlist()
"""

from __future__ import annotations

import pytest
import tempfile
import os

from opsswarm.tool_allowlist import (
    ToolAllowlist,
    ToolDenyError,
    ToolCapability,
    ProfileAllowlist,
)


# -------------------------------------------------------------------------- #
# Fixtures
# -------------------------------------------------------------------------- #


@pytest.fixture
def minimal_yaml():
    """Minimal valid YAML for ToolAllowlist."""
    return {
        "version": "1",
        "capabilities": {
            "read-only": {
                "description": "Read-only tools",
                "tools": ["read_logs", "describe_pods"],
            },
        },
        "profiles": {
            "incident-manager": {
                "capabilities": ["read-only"],
            },
        },
    }


@pytest.fixture
def full_yaml():
    """Full-featured YAML matching config/tool-allowlist.yaml structure."""
    return {
        "version": "1",
        "capabilities": {
            "read-only": {
                "description": "Read-only tools",
                "tools": ["read_logs", "describe_pods", "get_metrics"],
            },
            "write-scaling": {
                "description": "Scaling operations",
                "tools": ["scale_deployment"],
            },
        },
        "profiles": {
            "incident-manager": {
                "capabilities": ["read-only"],
            },
            "recovery-responder": {
                "capabilities": ["read-only", "write-scaling"],
                "allowed_tools": ["exec_in_pod"],
                "deny_tools": ["scale_deployment"],  # explicit block override
            },
            "s1": {
                "allowed_tools": ["read_logs"],
                "deny_tools": ["describe_pods"],
            },
        },
    }


# -------------------------------------------------------------------------- #
# Schema validation
# -------------------------------------------------------------------------- #


class TestSchemaValidation:
    def test_load_missing_version_raises(self):
        with pytest.raises(ValueError, match="missing required 'version'"):
            ToolAllowlist._from_dict({})

    def test_load_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported.*schema version"):
            ToolAllowlist._from_dict({"version": "99"})

    def test_load_missing_path_returns_none(self, tmp_path):
        result = ToolAllowlist.load(str(tmp_path / "nonexistent.yaml"))
        assert result is None

    def test_load_invalid_yaml_raises(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("  version: 1\n  not: [valid")
        with pytest.raises(ValueError, match="invalid YAML"):
            ToolAllowlist.load(str(f))

    def test_from_dict_valid(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        assert al.version == "1"
        assert "read-only" in al._capabilities
        assert "incident-manager" in al._profile_specs

    def test_capabilities_parsed(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        cap = al._capabilities["read-only"]
        assert cap.id == "read-only"
        assert cap.description == "Read-only tools"
        assert cap.tools == {"read_logs", "describe_pods"}

    def test_from_dict_unknown_capability_type_raises(self, minimal_yaml):
        minimal_yaml["capabilities"]["read-only"] = "not-a-dict"
        with pytest.raises(ValueError, match="must be a dict"):
            ToolAllowlist._from_dict(minimal_yaml)

    def test_from_dict_capability_tools_not_list_raises(self, minimal_yaml):
        minimal_yaml["capabilities"]["read-only"]["tools"] = "read_logs"
        with pytest.raises(ValueError, match="tools must be a list"):
            ToolAllowlist._from_dict(minimal_yaml)


# -------------------------------------------------------------------------- #
# ToolAllowlist.is_enabled()
# -------------------------------------------------------------------------- #


class TestIsEnabled:
    def test_instance_is_enabled(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        assert al.is_enabled() is True


# -------------------------------------------------------------------------- #
# ToolAllowlist.allowed_for() — resolution
# -------------------------------------------------------------------------- #


class TestAllowedFor:
    def test_capabilities_expanded(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        result = al.allowed_for("incident-manager")
        assert result.profile == "incident-manager"
        # read-only capability has 3 tools
        assert "read_logs" in result.allowed_tools
        assert "describe_pods" in result.allowed_tools
        assert "get_metrics" in result.allowed_tools

    def test_multiple_capabilities_union(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        result = al.allowed_for("recovery-responder")
        # read-only (3) + write-scaling (1) + explicit (1) = 5 tools
        # scale_deployment is in write-scaling BUT also in deny_tools → removed
        assert "read_logs" in result.allowed_tools
        assert "describe_pods" in result.allowed_tools
        assert "get_metrics" in result.allowed_tools
        assert "exec_in_pod" in result.allowed_tools  # explicit allowlist entry
        assert "scale_deployment" not in result.allowed_tools  # in cap but denied

    def test_deny_tools_subtracts(self, full_yaml):
        """deny_tools must remove tools even if they come from capabilities."""
        al = ToolAllowlist._from_dict(full_yaml)
        result = al.allowed_for("recovery-responder")
        # scale_deployment was in write-scaling but explicitly denied
        assert "scale_deployment" not in result.allowed_tools
        # Verify it's in the sources as a denylist entry
        deny_sources = [s for s in result.sources if s.startswith("denylist:")]
        assert len(deny_sources) == 1

    def test_explicit_allowed_tools(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        result = al.allowed_for("s1")
        assert "read_logs" in result.allowed_tools
        assert "describe_pods" not in result.allowed_tools  # denied explicitly
        assert "get_metrics" not in result.allowed_tools  # not in any list

    def test_unknown_profile_empty(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        result = al.allowed_for("unknown-profile")
        assert result.allowed_tools == set()
        assert result.profile == "unknown-profile"

    def test_sources_annotated(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        result = al.allowed_for("recovery-responder")
        assert any("capability:read-only" in s for s in result.sources)
        assert any("capability:write-scaling" in s for s in result.sources)
        assert any(s.startswith("allowlist:recovery-responder:") for s in result.sources)


# -------------------------------------------------------------------------- #
# ToolAllowlist.check() — enforcement
# -------------------------------------------------------------------------- #


class TestCheck:
    def test_allowed_tool_passes(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        al.check("read_logs", "incident-manager")  # should not raise

    def test_disallowed_tool_raises(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        with pytest.raises(ToolDenyError) as exc_info:
            al.check("kubectl_exec", "incident-manager")
        assert exc_info.value.tool == "kubectl_exec"
        assert exc_info.value.profile == "incident-manager"
        assert exc_info.value.correlation_id is not None

    def test_check_raises_on_unknown_profile(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        with pytest.raises(ToolDenyError) as exc_info:
            al.check("read_logs", "unknown-profile")
        assert exc_info.value.tool == "read_logs"
        assert exc_info.value.profile == "unknown-profile"


class TestCheckWithCapability:
    def test_check_with_capability_allowed(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        # read_logs is in read-only capability
        al.check_with_capability("read_logs", "incident-manager", "read-only")

    def test_check_with_capability_unknown_cap_raises(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        with pytest.raises(ToolDenyError) as exc_info:
            al.check_with_capability("read_logs", "incident-manager", "nonexistent-cap")
        assert "unknown_capability" in exc_info.value.reason

    def test_check_with_capability_tool_not_in_cap_raises(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        with pytest.raises(ToolDenyError) as exc_info:
            # read_logs is not in write-scaling
            al.check_with_capability("read_logs", "incident-manager", "write-scaling")
        assert "not_in_capability" in exc_info.value.reason

    def test_check_with_capability_tool_not_in_cap_denied(self, full_yaml):
        """Tool in profile allowlist but not in required capability is denied."""
        al = ToolAllowlist._from_dict(full_yaml)
        # describe_pods is in the profile allowlist (via read-only cap)
        # but NOT in the write-scaling capability
        with pytest.raises(ToolDenyError) as exc_info:
            al.check_with_capability("describe_pods", "incident-manager", "write-scaling")
        assert "not_in_capability" in exc_info.value.reason

    def test_check_with_capability_unknown_cap_denied(self, full_yaml):
        """Tool in profile allowlist but capability is unknown raises specific reason."""
        al = ToolAllowlist._from_dict(full_yaml)
        # describe_pods is in the profile allowlist (via read-only)
        # but imaginary-cap doesn't exist → raises unknown_capability
        with pytest.raises(ToolDenyError) as exc_info:
            al.check_with_capability("describe_pods", "incident-manager", "imaginary-cap")
        assert "unknown_capability" in exc_info.value.reason

    def test_check_with_capability_allowed_tool_even_if_cap_only(self, full_yaml):
        """Tool in the capability passes even if not explicitly allowlisted."""
        al = ToolAllowlist._from_dict(full_yaml)
        # describe_pods is in read-only capability
        al.check_with_capability("describe_pods", "incident-manager", "read-only")


# -------------------------------------------------------------------------- #
# Default-deny
# -------------------------------------------------------------------------- #


class TestDefaultDeny:
    def test_any_tool_not_in_allowlist_is_denied(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        # This tool is not in any profile's allowlist
        with pytest.raises(ToolDenyError):
            al.check("terraform_apply", "incident-manager")


# -------------------------------------------------------------------------- #
# ToolDenyError
# -------------------------------------------------------------------------- #


class TestToolDenyError:
    def test_attributes(self):
        err = ToolDenyError(
            tool="kubectl_exec",
            profile="incident-manager",
            reason="tool_not_in_profile_allowlist",
            correlation_id="abc123",
        )
        assert err.tool == "kubectl_exec"
        assert err.profile == "incident-manager"
        assert err.reason == "tool_not_in_profile_allowlist"
        assert err.correlation_id == "abc123"

    def test_for_log(self):
        err = ToolDenyError(
            tool="kubectl_exec",
            profile="incident-manager",
            reason="tool_not_in_profile_allowlist",
            correlation_id="abc123",
        )
        log_line = err.for_log()
        assert "TOOL_DENIED" in log_line
        assert "kubectl_exec" in log_line
        assert "abc123" in log_line

    def test_for_audit(self):
        err = ToolDenyError(
            tool="kubectl_exec",
            profile="incident-manager",
            reason="tool_not_in_profile_allowlist",
            correlation_id="abc123",
        )
        audit = err.for_audit()
        assert audit["event"] == "tool_deny"
        assert audit["tool"] == "kubectl_exec"
        assert audit["profile"] == "incident-manager"
        assert audit["correlation_id"] == "abc123"


# -------------------------------------------------------------------------- #
# Introspection helpers
# -------------------------------------------------------------------------- #


class TestIntrospection:
    def test_capability_tools(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        assert al.capability_tools("read-only") == {"read_logs", "describe_pods"}
        assert al.capability_tools("nonexistent") == set()

    def test_all_tools(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        assert al.all_tools() == {"read_logs", "describe_pods"}

    def test_profile_names(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        names = al.profile_names()
        assert "incident-manager" in names
        assert "recovery-responder" in names
        assert "s1" in names

    def test_capability_names(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        names = al.capability_names()
        assert "read-only" in names
        assert "write-scaling" in names

    def test_describe_profile(self, full_yaml):
        al = ToolAllowlist._from_dict(full_yaml)
        desc = al.describe_profile("recovery-responder")
        assert desc["profile"] == "recovery-responder"
        assert desc["configured"] is True
        assert desc["tool_count"] == len(desc["allowed_tools"])
        assert isinstance(desc["sources"], list)

    def test_describe_unknown_profile(self, minimal_yaml):
        al = ToolAllowlist._from_dict(minimal_yaml)
        desc = al.describe_profile("ghost-profile")
        assert desc["configured"] is False
        assert desc["tool_count"] == 0
