from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from typing import Any

from .errors import new_correlation_id, sanitize_for_comment, sanitize_for_log, OpenClawErrorSanitized
from .tool_allowlist import ToolAllowlist, ToolDenyError

logger = logging.getLogger(__name__)


class OpenClawError(RuntimeError): pass


class OpenClawClient:
    def __init__(
        self,
        binary: str = "openclaw",
        timeout: int = 600,
        *,
        check_tools: bool = False,
        tool_allowlist: ToolAllowlist | None = None,
    ):
        """Create an OpenClaw client.

        Args:
            binary: Path to the openclaw binary.
            timeout: Seconds before an individual call times out.
            check_tools: When True, enforce tool allowlist on every call.
                Defaults to False so existing tests continue to pass (D7 silent-disable).
            tool_allowlist: A loaded ToolAllowlist instance. Required when
                check_tools=True. When check_tools=False, this parameter is
                accepted but not used (backward compatibility).
        """
        self.binary = binary
        self.timeout = timeout
        self._check_tools = check_tools
        self._tool_allowlist: ToolAllowlist | None = tool_allowlist

    @property
    def tool_allowlist(self) -> ToolAllowlist | None:
        """The tool allowlist instance, or None if not configured."""
        return self._tool_allowlist

    def set_tool_allowlist(self, allowlist: ToolAllowlist | None) -> None:
        """Set or replace the tool allowlist at runtime.

        This allows the orchestrator to inject the allowlist after construction,
        once the config is loaded.  Idempotent: calling with None disables checks.
        """
        self._tool_allowlist = allowlist

    # ------------------------------------------------------------------ #
    # Tool enforcement
    # ------------------------------------------------------------------ #

    def _check_tool_access(self, tool: str, profile: str) -> None:
        """Raise ToolDenyError if the tool is not allowed for the profile.

        Enforcement point: called by run_text() / run_json() before passing
        the prompt to OpenClaw.  This is the ADR-027 injection point.
        """
        # D7 silent-disable: if allowlist is not configured, permit all tools
        if not self._check_tools or self._tool_allowlist is None:
            return

        self._tool_allowlist.check(tool, profile)

    # ------------------------------------------------------------------ #
    # OpenClaw invocation
    # ------------------------------------------------------------------ #

    async def run_text(
        self,
        agent: str,
        session_key: str,
        prompt: str,
        *,
        check_tools: bool | None = None,
    ) -> str:
        """Run OpenClaw and return the assistant's text response.

        Args:
            agent: The OpenClaw agent name (e.g. 'opsswarm-incident-manager').
            session_key: Unique session key for this run.
            prompt: The prompt text to send.
            check_tools: Override instance-level check_tools flag for this call.
                Pass True to enforce allowlist for a specific call, False to skip.
                Defaults to the instance-level setting.

        Raises:
            ToolDenyError: When a disallowed tool is detected (check_tools enabled).
            OpenClawErrorSanitized: When OpenClaw returns a non-zero exit code.
        """
        # ADR-027 enforcement point: check tool access before invocation
        _enforce = check_tools if check_tools is not None else self._check_tools
        if _enforce and self._tool_allowlist is not None:
            self._tool_allowlist.check(agent, agent)

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(prompt);
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                self.binary, "agent", "--agent", agent, "--session-key", session_key,
                "--message-file", path, "--json", "--timeout", str(self.timeout),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout + 30)
            if proc.returncode != 0:
                raw_stderr = err.decode(errors="replace")
                # Truncate before sanitization to limit log size
                truncated_stderr = raw_stderr[-1200:]
                corr_id = new_correlation_id()
                # Sanitize for log only — raw stderr (with correlation ID attached)
                # never reaches GitHub comments
                safe_stderr = sanitize_for_log(truncated_stderr)
                logger.error(f"OpenClaw rc={proc.returncode} [{corr_id}]: {safe_stderr}")
                # Raise with sanitised wrapper so callers can post a safe comment
                raise OpenClawErrorSanitized(
                    sanitize_for_comment(truncated_stderr),
                    correlation_id=corr_id,
                    is_stderr=True,
                )
            envelope = json.loads(out.decode())
            if not envelope.get("ok", True): raise OpenClawError(str(envelope.get("error")))
            if isinstance(envelope.get("final"), str): return envelope["final"]
            for p in envelope.get("payloads", []):
                if isinstance(p, dict) and isinstance(p.get("text"), str): return p["text"]
            # Gateway-backed response may nest payloads under result.
            result = envelope.get("result") or {}
            for p in result.get("payloads", []) if isinstance(result, dict) else []:
                if isinstance(p, dict) and isinstance(p.get("text"), str): return p["text"]
            raise OpenClawError("No assistant text in OpenClaw JSON envelope")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _extract_json(text: str) -> Any:
        s = text.strip()
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?\s*", "", s);
            s = re.sub(r"\s*```$", "", s)
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            # bounded salvage: first object or array only
            starts = [i for i in (s.find('{'), s.find('[')) if i >= 0]
            if not starts: raise
            start = min(starts);
            opening = s[start];
            closing = '}' if opening == '{' else ']'
            end = s.rfind(closing)
            if end <= start: raise
            return json.loads(s[start:end + 1])

    async def run_json(
        self,
        agent: str,
        session_key: str,
        prompt: str,
        *,
        check_tools: bool | None = None,
    ) -> Any:
        """Run OpenClaw and parse the response as JSON.

        Args:
            agent: The OpenClaw agent name.
            session_key: Unique session key for this run.
            prompt: The prompt text to send.
            check_tools: Override instance-level check_tools flag for this call.

        Raises:
            ToolDenyError: When a disallowed tool is detected (check_tools enabled).
            OpenClawErrorSanitized: When OpenClaw returns a non-zero exit code.
        """
        return self._extract_json(
            await self.run_text(agent, session_key, prompt, check_tools=check_tools)
        )
