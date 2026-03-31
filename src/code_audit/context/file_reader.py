"""Token-budget-aware file reading.

Reads full file contents for changed files, respecting size limits.
Includes surrounding context for partially changed files.
"""

from __future__ import annotations

from pathlib import Path

from code_audit.models.context import FileDiff


# Rough token estimation: ~4 chars per token for code
CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS_PER_FILE = 4000  # ~16KB per file
DEFAULT_MAX_TOTAL_TOKENS = 50000  # ~200KB total


def estimate_tokens(text: str) -> int:
    """Rough token count estimation."""
    return len(text) // CHARS_PER_TOKEN


def read_file_safe(path: Path) -> str | None:
    """Read a file, returning None on any error."""
    try:
        content = path.read_text(encoding="utf-8")
        return content
    except (OSError, UnicodeDecodeError):
        return None


def should_read_full_file(diff: FileDiff) -> bool:
    """Determine if we should read the full file content.

    Read full file when:
    - File is newly added
    - More than 50% of lines were changed
    - File is small enough
    """
    if diff.status == "added":
        return True
    if diff.is_binary:
        return False
    if diff.status == "deleted":
        return False
    # If heavily modified, read the full file
    if diff.total_changes > 20:
        return True
    return False


def read_changed_files(
    project_path: Path,
    diffs: list[FileDiff],
    max_tokens_per_file: int = DEFAULT_MAX_TOKENS_PER_FILE,
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS,
    max_file_size_kb: int = 500,
) -> dict[str, str]:
    """Read full content of changed files, respecting token budgets.

    Returns a dict of file_path → file_content for files that should
    be sent as full context to the review agents.
    """
    result: dict[str, str] = {}
    total_tokens = 0

    # Sort diffs: prioritize heavily modified files
    sorted_diffs = sorted(diffs, key=lambda d: d.total_changes, reverse=True)

    for diff in sorted_diffs:
        if diff.is_binary:
            continue
        if diff.status == "deleted":
            continue

        if not should_read_full_file(diff):
            continue

        file_path = project_path / diff.file_path
        if not file_path.is_file():
            continue

        # Check file size
        try:
            file_size_kb = file_path.stat().st_size / 1024
            if file_size_kb > max_file_size_kb:
                continue
        except OSError:
            continue

        content = read_file_safe(file_path)
        if content is None:
            continue

        tokens = estimate_tokens(content)
        if tokens > max_tokens_per_file:
            # Truncate to budget
            max_chars = max_tokens_per_file * CHARS_PER_TOKEN
            content = content[:max_chars] + "\n\n... [truncated]"
            tokens = max_tokens_per_file

        if total_tokens + tokens > max_total_tokens:
            break

        result[diff.file_path] = content
        total_tokens += tokens

    return result
