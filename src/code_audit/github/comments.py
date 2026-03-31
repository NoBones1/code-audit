"""PR comment formatter — maps findings to inline review comments.

Converts CodeAudit findings into GitHub Pull Request Review comments,
mapping each finding to the exact diff line where the issue was found.
"""

from __future__ import annotations

import re

from code_audit.github.client import GitHubClient
from code_audit.models.finding import Finding, Severity
from code_audit.models.report import AuditReport


SEVERITY_EMOJI = {
    Severity.IMPORTANT: "🔴",
    Severity.NIT: "🟡",
    Severity.PRE_EXISTING: "🟣",
}

SEVERITY_LABEL = {
    Severity.IMPORTANT: "Important",
    Severity.NIT: "Nit",
    Severity.PRE_EXISTING: "Pre-existing",
}


def format_finding_comment(finding: Finding) -> str:
    """Format a single finding as a GitHub inline comment body."""
    emoji = SEVERITY_EMOJI[finding.severity]
    label = SEVERITY_LABEL[finding.severity]

    lines = [
        f"### {emoji} {label}: {finding.title}",
        "",
        finding.description,
        "",
    ]

    if finding.suggestion:
        lines.extend([
            "<details>",
            "<summary>Suggested fix</summary>",
            "",
            finding.suggestion,
            "",
            "</details>",
            "",
        ])

    # Metadata line
    meta_parts = [f"**Confidence**: {finding.confidence:.0%}"]
    meta_parts.append(f"**Dimension**: {finding.dimension}")
    if finding.tags:
        tags_str = ", ".join(f"`{t}`" for t in finding.tags)
        meta_parts.append(f"**Tags**: {tags_str}")
    lines.append(" | ".join(meta_parts))

    return "\n".join(lines)


def format_review_body(report: AuditReport) -> str:
    """Format the top-level review body summarizing the audit."""
    s = report.summary

    if s.total_findings == 0:
        return (
            "## CodeAudit Review\n\n"
            "No issues found. The code looks clean.\n\n"
            f"*Reviewed {s.files_reviewed} files in {report.duration_seconds:.0f}s "
            f"({report.mode} mode)*"
        )

    lines = [
        "## CodeAudit Review",
        "",
        f"Found **{s.total_findings} findings** across {s.files_reviewed} files:",
        "",
        "| Severity | Count |",
        "|----------|-------|",
    ]

    if s.important > 0:
        lines.append(f"| 🔴 Important | {s.important} |")
    if s.nit > 0:
        lines.append(f"| 🟡 Nit | {s.nit} |")
    if s.pre_existing > 0:
        lines.append(f"| 🟣 Pre-existing | {s.pre_existing} |")

    lines.extend([
        "",
        f"*{report.mode} mode | {report.duration_seconds:.0f}s | "
        f"{', '.join(report.llm_providers_used)}*",
    ])

    # Machine-readable severity line (compatible with Claude Code Review format)
    severity_json = (
        f'{{"important": {s.important}, "nit": {s.nit}, '
        f'"pre_existing": {s.pre_existing}}}'
    )
    lines.extend([
        "",
        f"<!-- codeaudit-severity: {severity_json} -->",
    ])

    return "\n".join(lines)


def build_review_comments(
    findings: list[Finding],
    pr_files: list[dict],
) -> list[dict]:
    """Build GitHub review comment objects from findings.

    Maps each finding to the correct line in the PR diff.
    GitHub requires comments to reference lines that exist in the diff,
    so we validate against the PR's changed files.

    Args:
        findings: List of audit findings
        pr_files: List of PR file objects from GitHub API (with patch info)

    Returns:
        List of comment dicts ready for GitHub's create_review API
    """
    # Build a set of (file_path, line_number) pairs that exist in the diff
    diff_lines: dict[str, set[int]] = {}
    for pf in pr_files:
        filename = pf.get("filename", "")
        patch = pf.get("patch", "")
        if not patch:
            continue

        lines_in_diff: set[int] = set()
        current_line = 0
        for line in patch.split("\n"):
            if line.startswith("@@"):
                # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
                match = re.search(r"\+(\d+)", line)
                if match:
                    current_line = int(match.group(1)) - 1
                continue
            if line.startswith("-"):
                continue  # Deleted lines don't have a position in new file
            current_line += 1
            if line.startswith("+") or not line.startswith("\\"):
                lines_in_diff.add(current_line)

        diff_lines[filename] = lines_in_diff

    comments: list[dict] = []
    for finding in findings:
        path = finding.location.file_path
        line = finding.location.start_line

        # Only post inline comments on lines that exist in the diff
        if path in diff_lines:
            # Find the closest valid line if exact line isn't in diff
            valid_lines = diff_lines[path]
            if line in valid_lines:
                target_line = line
            else:
                # Find nearest valid line within 5 lines
                nearby = [l for l in valid_lines if abs(l - line) <= 5]
                if nearby:
                    target_line = min(nearby, key=lambda l: abs(l - line))
                else:
                    # Can't map to diff — skip inline, will be in review body
                    continue

            comments.append({
                "path": path,
                "line": target_line,
                "body": format_finding_comment(finding),
            })

    return comments


async def post_review_comments(
    client: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    report: AuditReport,
) -> dict | None:
    """Post the full audit as a GitHub PR review with inline comments.

    This is the main entry point for GitHub integration.

    Returns the created review object, or None if posting failed.
    """
    # Get PR info
    pr = await client.get_pr(owner, repo, pr_number)
    commit_sha = pr["head"]["sha"]

    # Get PR files for diff line mapping
    pr_files = await client.get_pr_files(owner, repo, pr_number)

    # Build inline comments
    inline_comments = build_review_comments(report.findings, pr_files)

    # Build review body
    body = format_review_body(report)

    # Any findings that couldn't be mapped to diff lines
    unmapped = []
    mapped_paths_lines = {(c["path"], c["line"]) for c in inline_comments}
    for f in report.findings:
        # Check if this finding was mapped to an inline comment
        found = False
        for c in inline_comments:
            if c["path"] == f.location.file_path:
                found = True
                break
        if not found:
            unmapped.append(f)

    # Add unmapped findings to the review body
    if unmapped:
        body += "\n\n### Additional findings\n\n"
        body += "*These findings couldn't be mapped to specific diff lines:*\n\n"
        for f in unmapped:
            emoji = SEVERITY_EMOJI[f.severity]
            body += (
                f"- {emoji} **{f.title}** — `{f.location.display}`\n"
                f"  {f.description}\n\n"
            )

    # Post the review
    try:
        review = await client.create_review(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            commit_sha=commit_sha,
            body=body,
            comments=inline_comments,
            event="COMMENT",  # Never approve or request changes — neutral only
        )
        return review
    except Exception:
        # Fall back to a simple comment if review creation fails
        try:
            await client.post_comment(owner, repo, pr_number, body)
        except Exception:
            pass
        return None
