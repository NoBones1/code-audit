"""Auto-fix engine — locates code snippets and applies LLM-generated fixes.

Called after the audit completes when the user opts in to fix application.
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path

from code_audit.models.finding import Finding
from code_audit.models.fix_response import FixResult

logger = logging.getLogger("code_audit.fixer")

_FIXER_PROMPT_PATH = Path(__file__).parent / "prompts" / "fixer.md"


def _load_fixer_prompt() -> str:
    """Load the fixer system prompt from the template file."""
    return _FIXER_PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Snippet location
# ---------------------------------------------------------------------------

def locate_snippet(
    file_content: str,
    snippet: str,
    start_line: int,
    window: int = 10,
) -> tuple[int, int] | None:
    """Find the character offsets of a snippet within a file.

    Tries exact substring match in a line window around start_line,
    then falls back to fuzzy matching with difflib.

    Returns:
        (start_offset, end_offset) character positions, or None if not found.
    """
    lines = file_content.split("\n")
    snippet_stripped = snippet.strip()

    if not snippet_stripped:
        return None

    # Build the search region (±window lines around start_line)
    region_start = max(0, start_line - 1 - window)
    region_end = min(len(lines), start_line + window)
    region_text = "\n".join(lines[region_start:region_end])

    # Exact substring match
    idx = region_text.find(snippet_stripped)
    if idx != -1:
        # Convert region-relative offset to file-absolute offset
        prefix = "\n".join(lines[:region_start])
        abs_start = len(prefix) + (1 if prefix else 0) + idx
        abs_end = abs_start + len(snippet_stripped)
        return (abs_start, abs_end)

    # Fuzzy match — try each window of snippet-length lines
    snippet_lines = snippet_stripped.split("\n")
    snippet_len = len(snippet_lines)

    best_ratio = 0.0
    best_range: tuple[int, int] | None = None

    for i in range(region_start, min(region_end, region_end - snippet_len + 1)):
        candidate_lines = lines[i : i + snippet_len]
        candidate = "\n".join(candidate_lines)
        ratio = difflib.SequenceMatcher(None, snippet_stripped, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            # Calculate character offsets
            prefix = "\n".join(lines[:i])
            abs_start = len(prefix) + (1 if prefix else 0)
            abs_end = abs_start + len(candidate)
            best_range = (abs_start, abs_end)

    if best_ratio >= 0.8 and best_range is not None:
        return best_range

    return None


# ---------------------------------------------------------------------------
# Fix generation (LLM call)
# ---------------------------------------------------------------------------

async def generate_fix(
    llm,
    original_snippet: str,
    suggestion: str,
    file_context: str,
    language: str | None = None,
) -> FixResult:
    """Call the LLM to produce a concrete code replacement.

    Args:
        llm: An LLM provider with complete_structured() method.
        original_snippet: The exact code to be replaced.
        suggestion: The textual suggestion from the finding.
        file_context: ~50 lines of surrounding code for context.
        language: Programming language (e.g., "python").

    Returns:
        FixResult with replacement code and metadata.
    """
    system_prompt = _load_fixer_prompt()

    user_prompt = (
        f"## Original Snippet\n```{language or ''}\n{original_snippet}\n```\n\n"
        f"## Suggested Fix\n{suggestion}\n\n"
        f"## File Context\n```{language or ''}\n{file_context}\n```\n\n"
        f"## Language\n{language or 'unknown'}"
    )

    return await llm.complete_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=FixResult,
        temperature=0.1,
        max_tokens=4096,
    )


# ---------------------------------------------------------------------------
# Fix application (produces diff, does NOT write)
# ---------------------------------------------------------------------------

def prepare_fix(
    file_content: str,
    start_offset: int,
    end_offset: int,
    replacement: str,
    file_path: str = "",
) -> tuple[str, str]:
    """Splice a replacement into file content and produce a unified diff.

    Args:
        file_content: Original file content.
        start_offset: Character offset where the original snippet starts.
        end_offset: Character offset where the original snippet ends.
        replacement: The replacement code string.
        file_path: File path for the diff header.

    Returns:
        (new_content, diff_str) — the modified file content and a unified diff.
    """
    new_content = file_content[:start_offset] + replacement + file_content[end_offset:]

    # Generate unified diff
    original_lines = file_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    )
    diff_str = "\n".join(diff)

    return new_content, diff_str


# ---------------------------------------------------------------------------
# High-level fix workflow for a single finding
# ---------------------------------------------------------------------------

async def fix_finding(
    finding: Finding,
    project_path: Path,
    llm,
) -> tuple[str | None, str | None, str | None]:
    """Attempt to fix a single finding.

    Returns:
        (new_content, diff_str, explanation) if fix was generated,
        (None, None, error_message) if fix could not be produced.
    """
    file_path = project_path / finding.location.file_path

    if not file_path.exists():
        return None, None, f"File not found: {finding.location.file_path}"

    file_content = file_path.read_text(encoding="utf-8")

    # Locate the snippet
    offsets = locate_snippet(
        file_content,
        finding.location.snippet,
        finding.location.start_line,
    )
    if offsets is None:
        return None, None, f"Could not locate snippet in {finding.location.file_path}"

    start_offset, end_offset = offsets
    original_snippet = file_content[start_offset:end_offset]

    # Get surrounding context (~25 lines before and after)
    lines = file_content.split("\n")
    ctx_start = max(0, finding.location.start_line - 1 - 25)
    ctx_end = min(len(lines), finding.location.start_line + 25)
    file_context = "\n".join(lines[ctx_start:ctx_end])

    # Generate the fix via LLM
    try:
        fix_result = await generate_fix(
            llm=llm,
            original_snippet=original_snippet,
            suggestion=finding.suggestion,
            file_context=file_context,
            language=finding.location.file_path.rsplit(".", 1)[-1] if "." in finding.location.file_path else None,
        )
    except Exception as e:
        return None, None, f"LLM fix generation failed: {e}"

    if fix_result.confidence < 0.3:
        return None, None, f"Fix confidence too low ({fix_result.confidence:.0%})"

    # Prepare the diff (don't write yet)
    new_content, diff_str = prepare_fix(
        file_content=file_content,
        start_offset=start_offset,
        end_offset=end_offset,
        replacement=fix_result.replacement_code,
        file_path=finding.location.file_path,
    )

    return new_content, diff_str, fix_result.explanation
