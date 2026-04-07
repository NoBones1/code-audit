"""Platform-aware comment formatting for PR/MR reviews.

Shared formatting (markdown body) is platform-agnostic.
Line-mapping differs per platform (GitHub path/line vs GitLab position vs Bitbucket inline).
"""

from __future__ import annotations

import re

from code_audit.models.finding import Finding
from code_audit.models.report import AuditReport


def format_finding_comment(finding: Finding) -> str:
    """Format a single finding as a markdown comment body (platform-agnostic)."""
    parts = [f"### {finding.severity.emoji} {finding.severity.label}: {finding.title}"]
    parts.append("")
    parts.append(finding.description)

    if finding.suggestion:
        parts.append("")
        parts.append("<details>")
        parts.append("<summary>Suggested fix</summary>")
        parts.append("")
        parts.append(finding.suggestion)
        parts.append("")
        parts.append("</details>")

    meta = []
    meta.append(f"**Confidence**: {finding.confidence:.0%}")
    meta.append(f"**Dimension**: {finding.dimension}")
    if finding.tags:
        meta.append(f"**Tags**: {', '.join(finding.tags)}")
    parts.append("")
    parts.append(" | ".join(meta))

    return "\n".join(parts)


def format_review_body(report: AuditReport) -> str:
    """Format the top-level review summary body (platform-agnostic markdown)."""
    s = report.summary
    lines = [
        "## CodeAudit Review Summary",
        "",
    ]

    severity_parts = []
    if s.important > 0:
        severity_parts.append(f"🔴 {s.important} Important")
    if s.nit > 0:
        severity_parts.append(f"🟡 {s.nit} Nit")
    if s.pre_existing > 0:
        severity_parts.append(f"🟣 {s.pre_existing} Pre-existing")

    if severity_parts:
        lines.append(" | ".join(severity_parts))
    else:
        lines.append("No issues found.")

    lines.append("")
    lines.append(
        f"Reviewed {s.files_reviewed} files in {report.duration_seconds:.0f}s "
        f"({report.mode} mode)"
    )

    if report.llm_providers_used:
        lines.append(f"Providers: {', '.join(report.llm_providers_used)}")

    return "\n".join(lines)


def build_inline_comments(
    findings: list[Finding],
    pr_files: list[dict],
) -> list[dict]:
    """Build inline comment dicts suitable for all platforms.

    Returns list of {"path": str, "line": int, "body": str} dicts.
    These are platform-agnostic — the platform adapter maps them
    to the specific API format (GitHub review comments, GitLab positions,
    Bitbucket inline objects).

    Only includes findings whose file/line can be mapped to the diff.
    """
    # Build a set of valid (file, line) pairs from PR files
    valid_lines: dict[str, set[int]] = {}
    for pf in pr_files:
        filename = pf.get("filename", "")
        patch = pf.get("patch", "")
        if not patch:
            continue

        lines_in_diff: set[int] = set()
        current_line = 0
        for patch_line in patch.split("\n"):
            hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", patch_line)
            if hunk_match:
                current_line = int(hunk_match.group(1))
                continue
            if patch_line.startswith("-"):
                continue
            if patch_line.startswith("+") or not patch_line.startswith("\\"):
                lines_in_diff.add(current_line)
                current_line += 1

        if lines_in_diff:
            valid_lines[filename] = lines_in_diff

    comments: list[dict] = []
    for finding in findings:
        fp = finding.location.file_path
        line = finding.location.start_line

        if fp not in valid_lines:
            continue

        diff_lines = valid_lines[fp]
        # Try exact line, then nearest within ±5
        target_line = line
        if line not in diff_lines:
            nearest = min(
                (l for l in diff_lines if abs(l - line) <= 5),
                key=lambda l: abs(l - line),
                default=None,
            )
            if nearest is None:
                continue
            target_line = nearest

        comments.append({
            "path": fp,
            "line": target_line,
            "body": format_finding_comment(finding),
        })

    return comments
