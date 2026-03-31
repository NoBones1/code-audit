"""Git diff extraction and structured parsing.

Implements hierarchical diff decomposition:
- File-level grouping
- Hunk-level parsing
- Noise reduction (lockfiles, binaries, whitespace-only)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from code_audit.config.defaults import EXTENSION_LANGUAGE_MAP
from code_audit.models.context import FileDiff, HunkDiff


# Regex patterns for diff parsing
DIFF_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
BINARY_RE = re.compile(r"^Binary files .* differ$")
RENAME_FROM_RE = re.compile(r"^rename from (.*)$")
RENAME_TO_RE = re.compile(r"^rename to (.*)$")

# Files to truncate or skip
LOCKFILE_EXTENSIONS = {".lock"}
LOCKFILE_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Gemfile.lock", "poetry.lock"}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".mp3", ".mp4", ".zip", ".tar", ".gz", ".pdf",
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".class",
}


_SAFE_REF_RE = re.compile(r"^[a-zA-Z0-9._\-/~^]+$")


def _validate_diff_target(diff_target: str) -> None:
    """Validate diff_target to prevent git argument injection."""
    if diff_target.startswith("-"):
        raise ValueError(f"Invalid diff target (cannot start with '-'): {diff_target}")
    if not _SAFE_REF_RE.match(diff_target):
        raise ValueError(f"Invalid diff target (contains disallowed characters): {diff_target}")


def run_git_diff(project_path: Path, diff_target: str = "HEAD") -> str:
    """Run git diff and return the raw output."""
    _validate_diff_target(diff_target)
    try:
        # git diff <ref> shows all changes (staged + unstaged) relative to <ref>
        result = subprocess.run(
            ["git", "diff", diff_target],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff_output = result.stdout

        # If diffing against a non-HEAD ref and no output, also check unstaged
        if not diff_output.strip() and diff_target != "HEAD":
            unstaged = subprocess.run(
                ["git", "diff"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            diff_output = unstaged.stdout

        return diff_output
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def detect_language(file_path: str) -> str | None:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(ext)


def is_lockfile(file_path: str) -> bool:
    """Check if a file is a lockfile."""
    name = Path(file_path).name
    ext = Path(file_path).suffix
    return name in LOCKFILE_NAMES or ext in LOCKFILE_EXTENSIONS


def is_binary_extension(file_path: str) -> bool:
    """Check if a file has a binary extension."""
    ext = Path(file_path).suffix.lower()
    return ext in BINARY_EXTENSIONS


def parse_hunks(hunk_text: str) -> list[HunkDiff]:
    """Parse hunk sections from diff text."""
    hunks: list[HunkDiff] = []
    current_header: str | None = None
    current_match: re.Match | None = None
    current_lines: list[str] = []

    for line in hunk_text.split("\n"):
        match = HUNK_HEADER_RE.match(line)
        if match:
            # Save previous hunk using its OWN parsed header
            if current_header and current_match:
                hunks.append(HunkDiff(
                    header=current_header,
                    old_start=int(current_match.group(1)),
                    old_count=int(current_match.group(2) or "1"),
                    new_start=int(current_match.group(3)),
                    new_count=int(current_match.group(4) or "1"),
                    content="\n".join(current_lines),
                ))
            current_header = line
            current_match = match
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)

    # Save last hunk
    if current_header and current_match:
        hunks.append(HunkDiff(
            header=current_header,
            old_start=int(current_match.group(1)),
            old_count=int(current_match.group(2) or "1"),
            new_start=int(current_match.group(3)),
            new_count=int(current_match.group(4) or "1"),
            content="\n".join(current_lines),
        ))

    return hunks


def parse_diff(raw_diff: str) -> list[FileDiff]:
    """Parse raw git diff output into structured FileDiff objects."""
    if not raw_diff.strip():
        return []

    files: list[FileDiff] = []
    # Split by diff headers
    sections = re.split(r"(?=^diff --git )", raw_diff, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        header_match = DIFF_HEADER_RE.match(section.split("\n")[0])
        if not header_match:
            continue

        old_path = header_match.group(1)
        new_path = header_match.group(2)

        # Check for binary
        if BINARY_RE.search(section) or is_binary_extension(new_path):
            files.append(FileDiff(
                file_path=new_path,
                old_path=old_path if old_path != new_path else None,
                status="modified",
                is_binary=True,
                language=detect_language(new_path),
            ))
            continue

        # Detect status
        status = "modified"
        if "new file mode" in section:
            status = "added"
        elif "deleted file mode" in section:
            status = "deleted"
        elif "rename from" in section:
            status = "renamed"

        # Parse hunks
        hunks = parse_hunks(section)

        # Count additions and deletions
        additions = 0
        deletions = 0
        for hunk in hunks:
            for line in hunk.content.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    additions += 1
                elif line.startswith("-") and not line.startswith("---"):
                    deletions += 1

        # Truncate lockfiles
        if is_lockfile(new_path) and hunks:
            # Keep only a summary
            truncated_content = f"[Lockfile changes: +{additions}/-{deletions} lines — truncated]"
            hunks = [HunkDiff(
                header="@@ -1,1 +1,1 @@",
                old_start=1, old_count=1, new_start=1, new_count=1,
                content=truncated_content,
            )]

        files.append(FileDiff(
            file_path=new_path,
            old_path=old_path if old_path != new_path else None,
            status=status,
            hunks=hunks,
            is_binary=False,
            language=detect_language(new_path),
            additions=additions,
            deletions=deletions,
        ))

    return files


def extract_diffs(project_path: Path, diff_target: str = "HEAD") -> list[FileDiff]:
    """Extract and parse git diffs from a project.

    This is the main entry point for diff extraction.
    """
    raw_diff = run_git_diff(project_path, diff_target)
    return parse_diff(raw_diff)
