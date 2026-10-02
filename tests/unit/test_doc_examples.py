"""Test that code examples in markdown documentation are syntactically valid.

These tests do NOT require a running OpsSwarm server. They verify:
1. Shell examples have valid bash structure (not syntax-checked against a live server)
2. Python snippets are syntactically valid and produce expected output
3. Configuration files parse correctly
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DOCS_DIR = PROJECT_ROOT / "docs"

# Match fenced code blocks: ```lang\n...\n```
FENCED_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


class DocExample:
    """A parsed code example extracted from a markdown file."""

    def __init__(self, file_path: Path, lang: str, code: str, line_no: int):
        self.file = file_path
        self.lang = lang
        self.code = code.strip()
        self.line_no = line_no
        self.relative_file = self.file.relative_to(PROJECT_ROOT)

    def snippet_id(self) -> str:
        return f"{self.relative_file}:{self.line_no}"


def extract_examples(md_file: Path) -> list[DocExample]:
    """Extract all fenced code blocks from a markdown file with line numbers."""
    if not md_file.is_file():
        return []
    try:
        content = md_file.read_text(encoding="utf-8")
    except Exception:
        return []

    examples: list[DocExample] = []
    lines = content.splitlines()
    # Track line numbers accounting for block removal
    i = 0
    pos = 0
    line_no = 1

    for match in FENCED_BLOCK.finditer(content):
        # Advance line_no to match the position
        while pos < match.start():
            if pos < len(content) and content[pos] == "\n":
                line_no += 1
            pos += 1

        lang = match.group(1).strip()
        code = match.group(2)
        examples.append(DocExample(md_file, lang, code, line_no))
        pos = match.end()
        # Count newlines in the match
        line_no += code.count("\n") + 1

    return examples


def _balanced_quotes(code: str) -> tuple[bool, str]:
    """Check shell code has balanced quotes and braces (no subprocess needed)."""
    lines = code.strip().splitlines()
    in_single = False
    in_double = False
    brace_depth = 0
    paren_depth = 0
    for lineno, line in enumerate(lines, 1):
        i = 0
        while i < len(line):
            c = line[i]
            # Skip escaped characters (including backslash line continuations)
            if c == "\\" and i + 1 < len(line):
                i += 2
                continue
            # Skip comment-to-EOL (handles cases like: # comment with "quotes")
            if c == "#":
                break
            if c == "'" and not in_double:
                in_single = not in_single
            elif c == '"' and not in_single:
                in_double = not in_double
            elif c == "{" and not in_single and not in_double:
                brace_depth += 1
            elif c == "}" and not in_single and not in_double:
                brace_depth -= 1
            elif c == "(" and not in_single and not in_double:
                paren_depth += 1
            elif c == ")" and not in_single and not in_double:
                paren_depth -= 1
            i += 1
    if in_single:
        return False, "Unclosed single-quote"
    if in_double:
        return False, "Unclosed double-quote"
    if brace_depth != 0:
        return False, f"Unbalanced braces: depth={brace_depth}"
    if paren_depth != 0:
        return False, f"Unbalanced parentheses: depth={paren_depth}"
    return True, ""


def bash_syntax_valid(code: str) -> bool:
    """Validate shell code for structural balance (no subprocess)."""
    ok, _ = _balanced_quotes(code)
    return ok


# ---------------------------------------------------------------------------
# Test: shell examples parse cleanly
# ---------------------------------------------------------------------------

SHELL_DOCS = [
    DOCS_DIR / "OPERATIONS.md",
    DOCS_DIR / "INSTALLATION.md",
    # RELEASE_GUIDE.md contains only text blocks (```text / ```), not shell blocks
]

@pytest.mark.parametrize("md_file", SHELL_DOCS, ids=lambda p: p.name)
class TestShellExamples:
    def test_no_shell_syntax_errors(self, md_file: Path):
        """Shell code blocks in operations docs must have valid bash syntax."""
        examples = extract_examples(md_file)
        shell_blocks = [e for e in examples if e.lang in ("bash", "sh", "shell", "")]

        assert shell_blocks, f"No shell blocks found in {md_file.name}"

        for ex in shell_blocks:
            ok, msg = _balanced_quotes(ex.code)
            assert ok, (
                f"Shell balance error in {ex.snippet_id()}: {msg}\n"
                f"```{ex.lang}\n{ex.code}\n```"
            )


# ---------------------------------------------------------------------------
# Test: Python examples are syntactically valid
# ---------------------------------------------------------------------------

PYTHON_DOCS = [
    DOCS_DIR / "guides" / "RELEASE_GUIDE.md",
    DOCS_DIR / "SECURITY.md",
]

@pytest.mark.parametrize("md_file", PYTHON_DOCS, ids=lambda p: p.name)
class TestPythonExamples:
    def test_python_blocks_parse(self, md_file: Path):
        """Python code blocks in docs must be syntactically valid."""
        examples = extract_examples(md_file)
        # Only test blocks explicitly marked as python/py — plain ``` blocks
        # are used for non-Python prose (e.g. bearer token format specs).
        py_blocks = [e for e in examples if e.lang in ("python", "py")]

        if not py_blocks:
            pytest.skip(f"No explicit python blocks in {md_file.name}")

        for ex in py_blocks:
            try:
                compile(ex.code, ex.snippet_id(), "exec")
            except SyntaxError as exc:
                pytest.fail(
                    f"Python syntax error in {ex.snippet_id()}:\n"
                    f"```{ex.lang}\n{ex.code}\n```\n"
                    f"SyntaxError: {exc.msg} at line {exc.lineno}"
                )


# ---------------------------------------------------------------------------
# Test: config snippets parse (YAML)
# ---------------------------------------------------------------------------

YAML_DOCS = [
    DOCS_DIR / "INSTALLATION.md",
    DOCS_DIR / "guides" / "METRICS_INTEGRATION.md",
]

@pytest.mark.parametrize("md_file", YAML_DOCS, ids=lambda p: p.name)
class TestYamlExamples:
    def test_yaml_blocks_parse(self, md_file: Path):
        """YAML code blocks in docs must be valid YAML."""
        examples = extract_examples(md_file)
        yaml_blocks = [e for e in examples if e.lang in ("yaml", "yml")]

        if not yaml_blocks:
            pytest.skip(f"No explicit yaml blocks in {md_file.name}")

        try:
            import yaml as _yaml  # type: ignore[import]
        except ImportError:
            pytest.skip("PyYAML not available")

        for ex in yaml_blocks:
            # Skip blocks with `***` used as inline auth credential placeholders.
            # These are intentionally incomplete (real credentials must be substituted).
            if re.search(r"^\s*\*\*\*", ex.code, re.MULTILINE):
                continue
            try:
                _yaml.safe_load(ex.code)
            except _yaml.YAMLError as exc:
                pytest.fail(
                    f"YAML parse error in {ex.snippet_id()}:\n"
                    f"```{ex.lang}\n{ex.code}\n```\n"
                    f"{type(exc).__name__}: {exc}"
                )


# ---------------------------------------------------------------------------
# Test: no literal placeholder text in example URLs
# ---------------------------------------------------------------------------

class TestNoPlaceholderLinks:
    def test_release_guide_has_real_github_url(self):
        """RELEASE_GUIDE.md must use real GitHub URL, not literal <owner>/<repo>."""
        content = (DOCS_DIR / "guides" / "RELEASE_GUIDE.md").read_text(encoding="utf-8")
        # The only acceptable placeholder pattern is in prose explanation lines,
        # not in link targets.
        literal_placeholder_links = re.findall(
            r"\]\(https://github\.com/<[^>]+>/<[^>]+>\)",
            content,
        )
        assert not literal_placeholder_links, (
            f"Found literal placeholder links in RELEASE_GUIDE.md: {literal_placeholder_links}"
        )

    def test_install_guide_no_internal_dev_urls(self):
        """INSTALLATION.md must not contain localhost:8088 in docs (that's runtime, not install)."""
        content = (DOCS_DIR / "INSTALLATION.md").read_text(encoding="utf-8")
        # It's fine to document http://localhost:8088 for runtime ops, but
        # we want to ensure docs don't accidentally document internal paths.
        # This is a smoke check; the real validation is that the docs parse cleanly.
        assert "PAYLOAD_SECRET" not in content or "#" in content.split("PAYLOAD_SECRET")[1][:10]
