# ADR-029 — Control-Character Sanitiser for Structured Log Injection Prevention

**Status:** Accepted
**Created:** 2026-10-03
**Issue:** [#58](https://github.com/vinhphan812/OpsSwarm-Enterprise/issues/58)
**CodeQL alerts:** py/log-injection #3 (github_client.py:35) and #4 (github_client.py:44)

## Context

Code Scanning flagged two `py/log-injection` MEDIUM alerts in `opsswarm/github_client.py`:

```python
# Alert #3 — github_client.py:35
logger.error(
    "GitHub API HTTP error: status=%s path=%s detail=%s",
    e.response.status_code,
    path,          # ← attacker-controlled
    e.response.text[:500],  # ← GitHub-controlled, may contain control chars
)

# Alert #4 — github_client.py:44
logger.exception("GitHub API unexpected error: method=%s path=%s", method, path)
```

An attacker who can control the `path` argument (via GitHub API redirect or malicious `base_url` — mitigated by ADR-028) could inject CRLF sequences into structured log fields, potentially forging log lines. Separately, GitHub's HTTP error bodies are developer-controlled from OpsSwarm's perspective and may contain newlines or other control characters.

The existing `sanitize_for_log()` function in `opsswarm/errors.py` already handled token redaction but had no control-character stripping.

## Decision

1. **Add `_strip_control_chars()` to `opsswarm/errors.py`.**
   Newlines (`\n`) are replaced with U+21A0 (↗ right arrow with upwards tip), a safe-to-log glyph that marks paragraph breaks without creating a new log line. Carriage returns (`\r`) are stripped. Tabs (`\t`) become a single space. All other C0 (NUL–US except TAB/LF/CR) and C1 (0x80–0x9F) control bytes are stripped. High bytes (Vietnamese CJK, emoji, etc.) are preserved.

2. **Wire `_strip_control_chars()` into both `sanitize_for_log()` and `sanitize_for_comment()`.**
   This means every code path that formats log output automatically benefits, not just `github_client.py`.

3. **Route all attacker-controlled or external data through `sanitize_for_log()` before passing to structured-log arguments in `github_client.py`.**
   Both `path` and `e.response.text` in the HTTPStatusError handler, and `method`/`path` in the generic exception handler, are sanitised.

4. **Do not modify the raised `PermissionError` message.**
   The PermissionError carries a structured string with method/path. Callers (`orchestrator.py`, `api.py`) are responsible for their own `sanitize_for_comment()` layer before posting to GitHub comments. This preserves debuggability while keeping the comment surface safe.

## Consequences

- **Positive:** Structured log fields are guaranteed single-line. Control characters in external HTTP bodies cannot forge log entries. Token redaction and control-char stripping are applied in one pass.
- **Positive:** The fix is central — all future callers of `sanitize_for_log()` automatically get control-char safety.
- **Negative:** Newline characters in log output are replaced with ↗; operators will see `"…↵…"` in multi-line error bodies. This is intentional — preserving observability while preventing injection.
- **Neutral:** The `_CONTROL_CHAR_RE` regex is documented with its character-range rationale; it is private (no `__all__` export) and stable.

## See also

- [ADR-028: Transport Boundary for GitHubClient (SSRF Mitigation)](./ADR-028_TRANSPORT_BOUNDARY_FOR_GITHUB_CLIENT.md)
- [SECURITY.md](../SECURITY.md) — fail-closed sanitisation policy
- `opsswarm/errors.py` — `_strip_control_chars`, `sanitize_for_log`, `sanitize_for_comment`
- `opsswarm/github_client.py` — `_req` exception handlers
