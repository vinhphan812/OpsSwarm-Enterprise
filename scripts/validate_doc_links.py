#!/usr/bin/env python3
"""Validate markdown links across documentation files.

Fail-closed validator that checks:
- Relative file and directory links exist
- Anchors within markdown documents resolve to existing headings
- Proper syntax and clean reporting for CI and local verification
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DOCS_DIR = PROJECT_ROOT / "docs"

# Regex for fenced code blocks
FENCED_CODE_BLOCK = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")
# Regex for inline code
INLINE_CODE = re.compile(r"`[^`\n]+`")
# Regex for markdown links: [text](target)
INLINE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
# Regex for reference definitions: [id]: target
REF_LINK_DEF = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)


class BrokenLink(NamedTuple):
    file_path: Path
    line_number: int
    link_text: str
    target: str
    resolved_path: Path
    reason: str


def slugify_heading(heading: str) -> str:
    """Convert a markdown heading string into a GitHub-style anchor slug."""
    # Strip leading hashes and whitespace
    text = heading.lstrip("#").strip()
    # Remove HTML tags if any
    text = re.sub(r"<[^>]+>", "", text)
    # Lowercase
    text = text.lower()
    # Replace spaces with hyphens, remove characters that aren't alphanumeric or hyphens/underscores
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    return text


def extract_headings(file_path: Path) -> set[str]:
    """Extract all heading anchor slugs from a markdown file."""
    if not file_path.is_file():
        return set()
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return set()

    # Strip code blocks
    content_no_code = FENCED_CODE_BLOCK.sub("", content)

    anchors = set()
    for line in content_no_code.splitlines():
        line = line.strip()
        if line.startswith("#"):
            slug = slugify_heading(line)
            if slug:
                anchors.add(slug)
    return anchors


def find_line_number(raw_content: str, target: str) -> int:
    """Approximate line number for target link in raw content."""
    lines = raw_content.splitlines()
    for i, line in enumerate(lines, 1):
        if target in line:
            return i
    return 1


def check_file_links(file_path: Path, base_dir: Path) -> list[BrokenLink]:
    """Check all links in a single markdown file."""
    broken: list[BrokenLink] = []
    try:
        raw_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        broken.append(
            BrokenLink(
                file_path=file_path,
                line_number=1,
                link_text="",
                target="",
                resolved_path=file_path,
                reason=f"Failed to read file: {e}",
            )
        )
        return broken

    # Mask out code blocks so we don't extract links from code examples
    masked_content = FENCED_CODE_BLOCK.sub(lambda m: "\n" * m.group().count("\n"), raw_content)
    masked_content = INLINE_CODE.sub(lambda m: " " * len(m.group()), masked_content)

    targets: list[tuple[str, str]] = []
    for match in INLINE_LINK.finditer(masked_content):
        targets.append(match.groups())
    for match in REF_LINK_DEF.finditer(masked_content):
        targets.append((match.group(1), match.group(2)))

    file_dir = file_path.parent

    for text, target in targets:
        target_clean = target.strip()
        # Skip external schemes and mailto
        if target_clean.startswith(("http://", "https://", "mailto:", "ftp://")):
            continue

        # Split path and anchor
        if "#" in target_clean:
            path_part, anchor_part = target_clean.split("#", 1)
        else:
            path_part, anchor_part = target_clean, ""

        line_num = find_line_number(raw_content, target)

        if not path_part and anchor_part:
            # Anchor on the same page
            headings = extract_headings(file_path)
            if anchor_part not in headings:
                broken.append(
                    BrokenLink(
                        file_path=file_path,
                        line_number=line_num,
                        link_text=text,
                        target=target,
                        resolved_path=file_path,
                        reason=f"Anchor '#{anchor_part}' not found in {file_path.name}",
                    )
                )
            continue

        resolved = (file_dir / path_part).resolve()

        if not resolved.exists():
            broken.append(
                BrokenLink(
                    file_path=file_path,
                    line_number=line_num,
                    link_text=text,
                    target=target,
                    resolved_path=resolved,
                    reason=f"Target path does not exist: {path_part}",
                )
            )
        elif anchor_part and resolved.is_file() and resolved.suffix.lower() == ".md":
            headings = extract_headings(resolved)
            if anchor_part not in headings:
                broken.append(
                    BrokenLink(
                        file_path=file_path,
                        line_number=line_num,
                        link_text=text,
                        target=target,
                        resolved_path=resolved,
                        reason=f"Anchor '#{anchor_part}' not found in target {resolved.name}",
                    )
                )

    return broken


def validate_documentation_links(
        docs_dir: Path,
        extra_files: list[Path] | None = None,
        verbose: bool = False,
) -> tuple[int, list[BrokenLink]]:
    """Validate links in all markdown files under docs_dir and any extra files."""
    all_files: list[Path] = []
    if docs_dir.exists():
        all_files.extend(sorted(docs_dir.rglob("*.md")))

    if extra_files:
        for f in extra_files:
            if f.exists() and f not in all_files:
                all_files.append(f)

    all_broken: list[BrokenLink] = []
    checked_files_count = len(all_files)

    for md_file in all_files:
        if verbose:
            print(f"Checking {md_file.relative_to(PROJECT_ROOT)}...")
        broken = check_file_links(md_file, docs_dir)
        all_broken.extend(broken)

    return checked_files_count, all_broken


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate markdown links in documentation.")
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DOCS_DIR,
        help=f"Directory containing docs (default: {DOCS_DIR})",
    )
    parser.add_argument(
        "--extra-files",
        nargs="*",
        type=Path,
        default=[PROJECT_ROOT / "README.md", PROJECT_ROOT / "AGENTS.md", PROJECT_ROOT / "CLAUDE.md"],
        help="Extra individual markdown files to check (e.g. root README.md)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output listing checked files",
    )

    args = parser.parse_args()

    print("==================================================")
    print(" OpsSwarm Documentation Link Validator")
    print("==================================================")
    print(f"Scanning directory: {args.docs_dir}")

    count, broken_links = validate_documentation_links(
        docs_dir=args.docs_dir,
        extra_files=args.extra_files,
        verbose=args.verbose,
    )

    print(f"Scanned {count} markdown files.")

    if broken_links:
        print(f"\n[FAIL] Found {len(broken_links)} broken link(s):\n")
        for b in broken_links:
            try:
                rel_path = b.file_path.relative_to(PROJECT_ROOT)
            except ValueError:
                rel_path = b.file_path
            print(f"  {rel_path}:{b.line_number}")
            print(f"    Link text: [{b.link_text}]({b.target})")
            print(f"    Problem:   {b.reason}")
            print(f"    Resolved:  {b.resolved_path}\n")
        return 1

    print("\n[PASS] All documentation links are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
