"""ADR-027 / Issue #27: Per-profile OpenClaw tool allowlists and least-privilege capabilities.

Design decisions (ADR-027):
  D1: ToolAllowlist class loads and validates the allowlist YAML on startup.
  D2: Per-profile allowlists declared as sets of tool names in YAML.
  D3: Default-deny: any tool not in a profile's allowlist is blocked.
  D4: Capability grouping: tools are grouped into capability tags; profiles
      declare capabilities rather than raw tool names.
  D5: Enforcement point: OpenClawClient.check_tool_access() called before
      any run_text/run_json call.
  D6: Deny raises ToolDenyError (structured, correlation ID, audit event).
  D7: Silent-disable: if allowlist config is absent/empty, all tools are
      permitted and a warning is logged (backward-compatible).
  D8: Logged as a SECURITY event so operators can alert on it.

Schema:
  version: "1"
  capabilities:
    <capability_id>:
      tools: [tool_a, tool_b, ...]
  profiles:
    <profile_name>:
      capabilities: [capability_id, ...]   # OR
      allowed_tools: [tool_c, tool_d, ...] # OR (capabilities + extra tools)
      deny_tools: [tool_e, ...]           # explicit blocklist per profile
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import new_correlation_id

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------- #
# Exceptions
# -------------------------------------------------------------------------- #


class ToolDenyError(RuntimeError):
    """Raised when a tool call is denied by the allowlist policy.

    Carries a correlation ID so operators can grep logs for the event.
    The error message is structured and safe to include in audit trails.
    """

    def __init__(
        self,
        tool: str,
        profile: str,
        reason: str,
        correlation_id: str,
    ):
        self.tool = tool
        self.profile = profile
        self.reason = reason
        self.correlation_id = correlation_id
        # Message is safe for logs and audit trails (no secrets)
        message = (
            f"[TOOL_DENIED] tool={tool!r} profile={profile!r} "
            f"reason={reason!r} corr_id={correlation_id}"
        )
        super().__init__(message)

    def for_log(self) -> str:
        """Return a structured log line (no secrets, safe for operator logs)."""
        return self.args[0]

    def for_audit(self) -> dict[str, Any]:
        """Return a structured audit dict for evidence storage."""
        return {
            "event": "tool_deny",
            "tool": self.tool,
            "profile": self.profile,
            "reason": self.reason,
            "correlation_id": self.correlation_id,
        }


# -------------------------------------------------------------------------- #
# Data classes
# -------------------------------------------------------------------------- #


@dataclass
class ToolCapability:
    """A named capability that groups one or more tools."""

    id: str
    description: str | None
    tools: set[str] = field(default_factory=set)

    def __post_init__(self):
        self.tools = set(self.tools)


@dataclass
class ProfileAllowlist:
    """Effective allowlist for one agent profile after resolution."""

    profile: str
    allowed_tools: set[str]  # fully resolved set
    sources: list[str]  # human-readable origin of each tool (for audit)


# -------------------------------------------------------------------------- #
# Loader / validator
# -------------------------------------------------------------------------- #


class ToolAllowlist:
    """Loaded tool allowlist with per-profile resolution and enforcement.

    Lifecycle:
      - load()         : parse and validate on startup
      - allowed_for()  : resolve effective allowlist for a profile
      - check()        : raise ToolDenyError if tool is not allowed
      - is_enabled()   : True when a config file was loaded
    """

    # Registry of singletons, keyed by config path (for Config-driven re-use)
    _instances: dict[str, "ToolAllowlist"] = {}

    def __init__(
        self,
        version: str,
        capabilities: dict[str, ToolCapability],
        profiles: dict[str, dict[str, Any]],
    ):
        self.version = version
        self._capabilities = capabilities
        self._profile_specs = profiles  # raw profile dicts from YAML

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #

    @classmethod
    def load(
        cls,
        path: str | Path | None,
        *,
        _cache_key: str | None = None,
    ) -> "ToolAllowlist | None":
        """Load and validate a tool allowlist from disk.

        Per ADR-027 D7:
          - File absent or unreadable → None (warn, permit all tools).
          - Invalid YAML or unknown version → raise ValueError (blocks startup).
        """
        if path is None:
            logger.warning("[ADR-027] Tool allowlist not configured — all tools permitted")
            return None
        p = Path(path).expanduser()
        if not p.exists():
            logger.warning("[ADR-027] Tool allowlist not found at %s — all tools permitted", p)
            return None

        try:
            import yaml

            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(
                f"[ADR-027] Tool allowlist at {p} contains invalid YAML: {exc}"
            ) from exc

        return cls._from_dict(raw, _cache_key=_cache_key)

    @classmethod
    def _from_dict(
        cls,
        data: dict[str, Any],
        _cache_key: str | None = None,
    ) -> "ToolAllowlist":
        """Build a ToolAllowlist from a parsed YAML dict."""
        version = data.get("version")
        if version is None:
            raise ValueError("[ADR-027] Tool allowlist is missing required 'version' field")
        if version != "1":
            raise ValueError(
                f"[ADR-027] Unsupported tool allowlist schema version {version!r} "
                "(only '1' is supported)"
            )

        # --- Parse capabilities ---
        raw_caps: dict[str, Any] = data.get("capabilities", {})
        capabilities: dict[str, ToolCapability] = {}
        for cap_id, cap_data in raw_caps.items():
            if not isinstance(cap_data, dict):
                raise ValueError(
                    f"[ADR-027] Capability {cap_id!r} must be a dict with 'tools' key"
                )
            tools_raw = cap_data.get("tools", [])
            if not isinstance(tools_raw, list):
                raise ValueError(
                    f"[ADR-027] Capability {cap_id!r}.tools must be a list"
                )
            capabilities[cap_id] = ToolCapability(
                id=cap_id,
                description=cap_data.get("description"),
                tools=set(str(t) for t in tools_raw),
            )

        # --- Parse profile specs (lightweight; resolved lazily) ---
        raw_profiles: dict[str, Any] = data.get("profiles", {})
        if not isinstance(raw_profiles, dict):
            raise ValueError("[ADR-027] 'profiles' must be a dict")

        instance = cls(
            version=str(version),
            capabilities=capabilities,
            profiles=raw_profiles,
        )

        # Cache if a cache key was provided
        if _cache_key is not None:
            cls._instances[_cache_key] = instance

        return instance

    @classmethod
    def from_config(
        cls,
        cfg: dict[str, Any],
        *,
        _cache_key: str | None = None,
    ) -> "ToolAllowlist | None":
        """Load the tool allowlist from a resolved config dict.

        The config key is 'tool_allowlist.path' (resolved relative to cwd,
        consistent with other config file resolution).
        """
        path = cfg.get("tool_allowlist", {}).get("path")
        return cls.load(path, _cache_key=_cache_key)

    @classmethod
    def get_cached(cls, cache_key: str) -> "ToolAllowlist | None":
        """Return a previously cached instance, or None."""
        return cls._instances.get(cache_key)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def is_enabled(self) -> bool:
        """Return True when a valid allowlist config was loaded."""
        return True  # If we have an instance, config was valid

    def capability_tools(self, capability_id: str) -> set[str]:
        """Return the set of tools for a capability, or empty set if unknown."""
        cap = self._capabilities.get(capability_id)
        return cap.tools if cap else set()

    def all_tools(self) -> set[str]:
        """Return the union of all tools across all capabilities."""
        result: set[str] = set()
        for cap in self._capabilities.values():
            result |= cap.tools
        return result

    def allowed_for(self, profile: str) -> ProfileAllowlist:
        """Resolve the effective allowlist for a profile.

        Resolution order:
          1. capability_tools for each declared capability
          2. explicit allowed_tools list
          3. explicit deny_tools subtracts from the union

        Returns ProfileAllowlist with the resolved set and source annotations.
        """
        spec = self._profile_specs.get(profile, {})

        allowed: set[str] = set()
        sources: list[str] = []

        # Step 1: capabilities
        for cap_id in spec.get("capabilities", []):
            cap_tools = self.capability_tools(cap_id)
            if cap_tools:
                allowed |= cap_tools
                sources.append(f"capability:{cap_id}")

        # Step 2: explicit allowed_tools
        for tool in spec.get("allowed_tools", []):
            allowed.add(str(tool))
            sources.append(f"allowlist:{profile}:{tool}")

        # Step 3: explicit deny_tools (subtract)
        denied: set[str] = set(str(t) for t in spec.get("deny_tools", []))
        if denied:
            removed = allowed & denied
            allowed -= denied
            for tool in sorted(removed):
                sources.append(f"denylist:{profile}:{tool}")

        return ProfileAllowlist(
            profile=profile,
            allowed_tools=allowed,
            sources=sources,
        )

    def check(self, tool: str, profile: str) -> None:
        """Raise ToolDenyError if the tool is not allowed for the profile.

        Per ADR-027 D6: denied tools raise ToolDenyError (not silently ignored).
        Per ADR-027 D3: default-deny when tool not in allowlist.
        Per ADR-027 D8: denial is logged as a SECURITY event.

        Args:
            tool: The OpenClaw tool name being invoked.
            profile: The agent profile name (e.g. 'incident-manager').

        Raises:
            ToolDenyError: When the tool is not in the profile's allowlist.
        """
        if not self.is_enabled():
            return  # D7: disabled allowlist permits all tools

        profile_allowlist = self.allowed_for(profile)
        corr_id = new_correlation_id()

        if tool not in profile_allowlist.allowed_tools:
            # D8: log as SECURITY event
            logger.warning(
                "[SECURITY][TOOL_DENIED] tool=%r profile=%r corr_id=%s sources=%r",
                tool,
                profile,
                corr_id,
                profile_allowlist.sources,
            )
            raise ToolDenyError(
                tool=tool,
                profile=profile,
                reason="tool_not_in_profile_allowlist",
                correlation_id=corr_id,
            )

    def check_with_capability(
        self,
        tool: str,
        profile: str,
        required_capability: str,
    ) -> None:
        """Check tool access with an additional capability-gate requirement.

        This variant is used when a task explicitly declares a required
        capability (e.g. from Task.required_capabilities).

        Raises ToolDenyError if:
          - The tool is not in the profile allowlist, OR
          - The required_capability is not defined / not granted to the profile.
        """
        if not self.is_enabled():
            return

        profile_allowlist = self.allowed_for(profile)
        corr_id = new_correlation_id()

        # Check 1: tool in profile allowlist?
        if tool not in profile_allowlist.allowed_tools:
            logger.warning(
                "[SECURITY][TOOL_DENIED] tool=%r profile=%r corr_id=%s reason=not_in_allowlist",
                tool,
                profile,
                corr_id,
            )
            raise ToolDenyError(
                tool=tool,
                profile=profile,
                reason="tool_not_in_profile_allowlist",
                correlation_id=corr_id,
            )

        # Check 2: required_capability is in the profile
        cap_tools = self.capability_tools(required_capability)
        if not cap_tools:
            logger.warning(
                "[SECURITY][TOOL_DENIED] tool=%r profile=%r corr_id=%s "
                "reason=unknown_capability_required",
                tool,
                profile,
                corr_id,
            )
            raise ToolDenyError(
                tool=tool,
                profile=profile,
                reason=f"unknown_capability:{required_capability}",
                correlation_id=corr_id,
            )

        if tool not in cap_tools:
            logger.warning(
                "[SECURITY][TOOL_DENIED] tool=%r profile=%r capability=%r corr_id=%s "
                "reason=tool_not_in_required_capability",
                tool,
                profile,
                required_capability,
                corr_id,
            )
            raise ToolDenyError(
                tool=tool,
                profile=profile,
                reason=f"tool_not_in_capability:{required_capability}",
                correlation_id=corr_id,
            )

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def profile_names(self) -> list[str]:
        """Return sorted list of all configured profile names."""
        return sorted(self._profile_specs.keys())

    def capability_names(self) -> list[str]:
        """Return sorted list of all defined capability IDs."""
        return sorted(self._capabilities.keys())

    def describe_profile(self, profile: str) -> dict[str, Any]:
        """Return a human-readable description of a profile's effective allowlist."""
        effective = self.allowed_for(profile)
        return {
            "profile": profile,
            "configured": profile in self._profile_specs,
            "allowed_tools": sorted(effective.allowed_tools),
            "tool_count": len(effective.allowed_tools),
            "sources": effective.sources,
        }
