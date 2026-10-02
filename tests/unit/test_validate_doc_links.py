"""Unit tests for scripts/validate_doc_links.py."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from validate_doc_links import (
    BrokenLink,
    check_file_links,
    extract_headings,
    find_line_number,
    slugify_heading,
    validate_documentation_links,
)


# ---------------------------------------------------------------------------
# slugify_heading
# ---------------------------------------------------------------------------

class TestSlugifyHeading:
    def test_basic(self):
        assert slugify_heading("## Hello World") == "hello-world"

    def test_strips_leading_hashes(self):
        assert slugify_heading("##### Deep heading") == "deep-heading"

    def test_lowercases(self):
        assert slugify_heading("# IMPORTANT Notice") == "important-notice"

    def test_replaces_spaces_with_hyphens(self):
        assert slugify_heading("## One   Two   Three") == "one-two-three"

    def test_strips_non_alphanumeric(self):
        assert slugify_heading("## Hello, World! (2024)") == "hello-world-2024"

    def test_removes_html_tags(self):
        # HTML tags are stripped; remaining text is slugified
        assert slugify_heading("## <script>alert</script>") == "alert"

    def test_empty_after_strip(self):
        assert slugify_heading("#") == ""


# ---------------------------------------------------------------------------
# find_line_number
# ---------------------------------------------------------------------------

class TestFindLineNumber:
    def test_finds_exact_target(self):
        content = "line 0\nline 1\nline 2\n"
        assert find_line_number(content, "line 1") == 2

    def test_returns_one_if_not_found(self):
        content = "line 0\nline 1\n"
        assert find_line_number(content, "missing") == 1

    def test_first_occurrence(self):
        content = "a\nb\na\n"
        assert find_line_number(content, "a") == 1


# ---------------------------------------------------------------------------
# extract_headings
# ---------------------------------------------------------------------------

class TestExtractHeadings:
    def test_extracts_all_levels(self, tmp_path: Path):
        md = tmp_path / "test.md"
        md.write_text("# H1\n## H2\n### H3\n", encoding="utf-8")
        headings = extract_headings(md)
        assert headings == {"h1", "h2", "h3"}

    def test_skips_code_blocks(self, tmp_path: Path):
        md = tmp_path / "test.md"
        md.write_text("# Heading\n```\n# Inside code\n```\n## After\n", encoding="utf-8")
        headings = extract_headings(md)
        assert headings == {"heading", "after"}

    def test_missing_file_returns_empty(self):
        assert extract_headings(Path("nonexistent.md")) == set()


# ---------------------------------------------------------------------------
# check_file_links — mocked filesystem
# ---------------------------------------------------------------------------

class TestCheckFileLinks:
    def test_broken_internal_path(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        doc_file = doc_dir / "test.md"
        doc_file.write_text("[link](nonexistent.md)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert len(broken) == 1
        assert "nonexistent.md" in broken[0].reason

    def test_valid_relative_link(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        target = doc_dir / "target.md"
        target.write_text("# Target Heading\n", encoding="utf-8")
        doc_file = doc_dir / "test.md"
        doc_file.write_text("[link](target.md)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert broken == []

    def test_broken_anchor_same_file(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        doc_file = doc_dir / "test.md"
        doc_file.write_text("# Real Heading\n[link](#missing-anchor)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert len(broken) == 1
        assert "missing-anchor" in broken[0].reason

    def test_valid_anchor_same_file(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        doc_file = doc_dir / "test.md"
        doc_file.write_text("# My Heading\n[link](#my-heading)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert broken == []

    def test_broken_anchor_cross_file(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        target = doc_dir / "target.md"
        target.write_text("# Target Heading\n", encoding="utf-8")
        doc_file = doc_dir / "test.md"
        doc_file.write_text("[link](target.md#missing-anchor)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert len(broken) == 1
        assert "missing-anchor" in broken[0].reason

    def test_valid_anchor_cross_file(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        target = doc_dir / "target.md"
        target.write_text("# My Anchor\n", encoding="utf-8")
        doc_file = doc_dir / "test.md"
        doc_file.write_text("[link](target.md#my-anchor)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert broken == []

    def test_skips_http_links(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        doc_file = doc_dir / "test.md"
        doc_file.write_text("[link](https://example.com)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert broken == []

    def test_skips_code_blocks(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        doc_file = doc_dir / "test.md"
        doc_file.write_text("```\n[link](nonexistent.md)\n```\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert broken == []

    def test_valid_subdirectory_link(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        sub = doc_dir / "sub"
        sub.mkdir()
        target = sub / "target.md"
        target.write_text("# Sub Target\n", encoding="utf-8")
        doc_file = doc_dir / "test.md"
        doc_file.write_text("[link](sub/target.md)\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert broken == []

    def test_reference_style_links(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        doc_file = doc_dir / "test.md"
        doc_file.write_text("[link]: nonexistent.md\n", encoding="utf-8")

        broken = check_file_links(doc_file, doc_dir)
        assert len(broken) == 1
        assert "nonexistent.md" in broken[0].reason


# ---------------------------------------------------------------------------
# validate_documentation_links — integration
# ---------------------------------------------------------------------------

class TestValidateDocumentationLinks:
    def test_returns_count_and_broken_list(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        good = doc_dir / "good.md"
        good.write_text("# Good\n", encoding="utf-8")
        bad = doc_dir / "bad.md"
        bad.write_text("[broken](missing.md)\n", encoding="utf-8")

        count, broken = validate_documentation_links(doc_dir)
        assert count == 2
        assert len(broken) == 1

    def test_extra_files_included(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        doc_dir.joinpath("doc.md").write_text("# Doc\n", encoding="utf-8")

        extra = tmp_path / "extra.md"
        extra.write_text("[broken](missing.md)\n", encoding="utf-8")

        _, broken = validate_documentation_links(doc_dir, extra_files=[extra])
        assert len(broken) == 1
