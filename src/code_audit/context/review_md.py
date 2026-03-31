"""REVIEW.md parser -- compatible with Claude Code Review's format.

Expected format:
    ## Always check
    - Rule 1
    - Rule 2

    ## Style
    - Preference 1

    ## Skip
    - Pattern to skip
"""

from __future__ import annotations

import re
from pathlib import Path

from code_audit.models.context import ReviewRules


# Section header patterns (case-insensitive)
ALWAYS_CHECK_RE = re.compile(r"^##\s*(always\s+check|mandatory|must\s+check|required)", re.IGNORECASE)
STYLE_RE = re.compile(r"^##\s*(style|conventions?|preferences?)", re.IGNORECASE)
SKIP_RE = re.compile(r"^##\s*(skip|ignore|exclude|don'?t\s+check)", re.IGNORECASE)
SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)
LIST_ITEM_RE = re.compile(r"^\s*[-*]\s+(.+)$")


def _extract_list_items(text: str) -> list[str]:
    """Extract markdown list items from a text block."""
    items: list[str] = []
    for line in text.strip().split("\n"):
        match = LIST_ITEM_RE.match(line)
        if match:
            items.append(match.group(1).strip())
    return items


def parse_review_md(project_path: Path) -> ReviewRules | None:
    """Parse REVIEW.md from the project root.

    Returns None if no REVIEW.md is found.
    """
    review_path = project_path / "REVIEW.md"
    if not review_path.is_file():
        return None

    try:
        content = review_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    if not content.strip():
        return None

    mandatory: list[str] = []
    style: list[str] = []
    skip: list[str] = []

    # Split into sections by ## headers
    lines = content.split("\n")
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if ALWAYS_CHECK_RE.match(line):
            # Save previous section
            if current_section == "mandatory":
                mandatory.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "style":
                style.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "skip":
                skip.extend(_extract_list_items("\n".join(current_lines)))
            current_section = "mandatory"
            current_lines = []
        elif STYLE_RE.match(line):
            if current_section == "mandatory":
                mandatory.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "style":
                style.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "skip":
                skip.extend(_extract_list_items("\n".join(current_lines)))
            current_section = "style"
            current_lines = []
        elif SKIP_RE.match(line):
            if current_section == "mandatory":
                mandatory.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "style":
                style.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "skip":
                skip.extend(_extract_list_items("\n".join(current_lines)))
            current_section = "skip"
            current_lines = []
        elif SECTION_RE.match(line):
            # Unknown section -- flush current
            if current_section == "mandatory":
                mandatory.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "style":
                style.extend(_extract_list_items("\n".join(current_lines)))
            elif current_section == "skip":
                skip.extend(_extract_list_items("\n".join(current_lines)))
            current_section = None
            current_lines = []
        else:
            current_lines.append(line)

    # Flush final section
    if current_section == "mandatory":
        mandatory.extend(_extract_list_items("\n".join(current_lines)))
    elif current_section == "style":
        style.extend(_extract_list_items("\n".join(current_lines)))
    elif current_section == "skip":
        skip.extend(_extract_list_items("\n".join(current_lines)))

    rules = ReviewRules(
        mandatory_checks=mandatory,
        style_rules=style,
        skip_rules=skip,
    )

    return rules if rules.has_rules else None


def find_claude_md(project_path: Path) -> str | None:
    """Read CLAUDE.md from the project root if it exists."""
    claude_path = project_path / "CLAUDE.md"
    if not claude_path.is_file():
        return None
    try:
        content = claude_path.read_text(encoding="utf-8")
        return content.strip() if content.strip() else None
    except (OSError, UnicodeDecodeError):
        return None
