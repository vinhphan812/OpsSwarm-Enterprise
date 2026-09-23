from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from typing import Any


class OpenClawError(RuntimeError): pass


class OpenClawClient:
    def __init__(self, binary="openclaw", timeout=600):
        self.binary = binary;
        self.timeout = timeout

    async def run_text(self, agent: str, session_key: str, prompt: str) -> str:
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
                raise OpenClawError(f"OpenClaw failed rc={proc.returncode}: {err.decode(errors='replace')[-1200:]}")
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

    async def run_json(self, agent: str, session_key: str, prompt: str) -> Any:
        return self._extract_json(await self.run_text(agent, session_key, prompt))
