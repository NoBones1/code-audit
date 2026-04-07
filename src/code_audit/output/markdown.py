"""Markdown report generator."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from code_audit.models.finding import Severity
from code_audit.models.report import AuditReport


def render_markdown_report(report: AuditReport) -> str:
    """Generate a markdown report from the audit results."""
    lines: list[str] = []

    # Header
    lines.append("# Code Audit Report")
    lines.append("")
    lines.append(f"**Audit ID**: `{report.audit_id}`")
    lines.append(f"**Date**: {report.timestamp.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Project**: `{report.target_path}`")
    lines.append(f"**Mode**: {report.mode}")
    lines.append(f"**Diff target**: `{report.diff_target}`")
    lines.append(f"**Duration**: {report.duration_seconds:.1f}s")
    lines.append(f"**Providers**: {', '.join(report.llm_providers_used)}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    s = report.summary
    if s.total_findings == 0:
        lines.append("No issues found. The code looks clean.")
    else:
        lines.append(f"| Metric | Count |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total findings | **{s.total_findings}** |")
        lines.append(f"| 🔴 Important | {s.important} |")
        lines.append(f"| 🟡 Nit | {s.nit} |")
        lines.append(f"| 🟣 Pre-existing | {s.pre_existing} |")
        lines.append(f"| Files reviewed | {s.files_reviewed} |")
    lines.append("")

    # Dimension breakdown
    if s.dimension_summaries:
        lines.append("### By Dimension")
        lines.append("")
        lines.append("| Dimension | Findings | Important | Nit | Pre-existing | Avg Confidence | Model | Duration |")
        lines.append("|-----------|----------|-----------|-----|-------------|---------------|-------|----------|")
        for ds in s.dimension_summaries:
            lines.append(
                f"| {ds.dimension} | {ds.total_findings} | {ds.important} | "
                f"{ds.nit} | {ds.pre_existing} | {ds.avg_confidence:.0%} | {ds.agent_model} | {ds.duration_seconds:.1f}s |"
            )
        lines.append("")

    # Compliance coverage (CWE/OWASP mapping)
    owasp_findings: dict[str, list] = {}
    owasp_cwes: dict[str, set[str]] = {}
    for f in report.findings:
        for cat in f.owasp_categories:
            owasp_findings.setdefault(cat, []).append(f)
            owasp_cwes.setdefault(cat, set()).update(f.cwe_ids)

    if owasp_findings:
        lines.append("### Compliance Coverage (OWASP 2021)")
        lines.append("")
        lines.append("| OWASP Category | Findings | CWEs |")
        lines.append("|---------------|----------|------|")
        for cat in sorted(owasp_findings.keys()):
            cwes = ", ".join(sorted(owasp_cwes[cat]))
            lines.append(f"| {cat} | {len(owasp_findings[cat])} | {cwes} |")
        lines.append("")

    if not report.findings:
        return "\n".join(lines)

    # Secrets scan results
    secrets = [f for f in report.findings if f.dimension == "secrets"]
    if secrets:
        lines.append("\n## Secrets Scan\n")
        lines.append(f"Found **{len(secrets)}** potential secrets/credentials:\n")
        for f in secrets:
            lines.append(f"### {f.severity.emoji} {f.title}")
            lines.append(f"**{f.location.display}** | Confidence: {f.confidence:.0%}")
            lines.append(f"\n{f.description}\n")
            if f.suggestion:
                lines.append(f"> **Action**: {f.suggestion}\n")

    # Dependency vulnerability scan results
    dep_vulns = [f for f in report.findings if f.dimension == "dependencies"]
    if dep_vulns:
        lines.append("\n## Dependency Vulnerabilities\n")
        lines.append(f"Found **{len(dep_vulns)}** vulnerable dependencies:\n")
        for f in dep_vulns:
            lines.append(f"### {f.severity.emoji} {f.title}")
            lines.append(f"**{f.location.display}** | Confidence: {f.confidence:.0%}")
            lines.append(f"\n{f.description}\n")
            if f.suggestion:
                lines.append(f"> **Action**: {f.suggestion}\n")

    # Findings by severity
    findings_by_severity = report.findings_by_severity

    for severity in [Severity.IMPORTANT, Severity.NIT, Severity.PRE_EXISTING]:
        findings = findings_by_severity.get(severity, [])
        if not findings:
            continue

        lines.append(f"## {severity.emoji} {severity.label} ({len(findings)})")
        lines.append("")

        for finding in findings:
            lines.append(f"### {finding.title}")
            lines.append("")
            lines.append(f"**Location**: `{finding.location.display}`")
            lines.append(f"**Dimension**: {finding.dimension}")
            lines.append(f"**Confidence**: {finding.confidence:.0%}")
            if finding.tags:
                lines.append(f"**Tags**: {', '.join(f'`{t}`' for t in finding.tags)}")
            lines.append("")
            lines.append(finding.description)
            lines.append("")

            if finding.location.snippet:
                lines.append("```")
                lines.append(finding.location.snippet)
                lines.append("```")
                lines.append("")

            if finding.suggestion:
                lines.append(f"**Suggestion**: {finding.suggestion}")
                lines.append("")

            lines.append("---")
            lines.append("")

    # Cost breakdown
    if report.usage:
        lines.append("\n## Cost Breakdown\n")
        lines.append("| Agent | Model | Input Tokens | Output Tokens | Cost |")
        lines.append("|-------|-------|-------------|--------------|------|")
        for record in report.usage:
            cost_str = f"${record.cost_usd:.4f}" if record.cost_usd > 0 else "$0.00"
            model_short = record.model.split("/")[-1] if "/" in record.model else record.model
            lines.append(f"| {record.agent_name.title()} | {model_short} | {record.input_tokens:,} | {record.output_tokens:,} | {cost_str} |")

        total_input = sum(r.input_tokens for r in report.usage)
        total_output = sum(r.output_tokens for r in report.usage)
        total_cost = f"${report.total_cost_usd:.4f}" if report.total_cost_usd > 0 else "$0.00"
        lines.append(f"| **Total** | | **{total_input:,}** | **{total_output:,}** | **{total_cost}** |")

        if report.total_cost_usd == 0:
            lines.append(f"\n*All agents used free-tier providers. No charges incurred.*")

    # Footer
    lines.append("")
    lines.append("---")
    lines.append(f"*Generated by CodeAudit v0.2.0 at {report.timestamp.strftime('%Y-%m-%d %H:%M UTC')}*")

    return "\n".join(lines)


def write_markdown_report(report: AuditReport, output_path: Path) -> None:
    """Write the markdown report to a file."""
    content = render_markdown_report(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
