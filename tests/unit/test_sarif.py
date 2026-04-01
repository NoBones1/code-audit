"""Unit tests for SARIF output generation."""

import json
import pytest
from pathlib import Path

from code_audit.models.finding import Finding, FindingLocation, Severity
from code_audit.models.report import AuditReport, AuditSummary
from code_audit.output.sarif_writer import (
    write_sarif,
    _build_sarif_dict,
    SEVERITY_TO_SARIF_LEVEL,
    SARIF_SCHEMA_URI,
)


def _make_finding(
    title: str = "Test issue",
    severity: Severity = Severity.IMPORTANT,
    dimension: str = "security",
    file_path: str = "src/app.py",
    start_line: int = 10,
    end_line: int | None = None,
    suggestion: str | None = "Fix it",
) -> Finding:
    return Finding(
        dimension=dimension,
        severity=severity,
        title=title,
        description="Detailed description of the issue.",
        location=FindingLocation(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            snippet="problematic_code()",
        ),
        suggestion=suggestion,
        confidence=0.9,
        tags=["test-tag"],
    )


def _make_report(findings: list[Finding] | None = None) -> AuditReport:
    findings = findings or [_make_finding()]
    summary = AuditSummary.from_findings(
        findings=findings,
        files_reviewed=1,
        dimensions=["security"],
    )
    return AuditReport(
        audit_id="test-audit-123",
        target_path="/tmp/project",
        mode="deep",
        findings=findings,
        summary=summary,
        duration_seconds=5.0,
    )


# ── SARIF structure ───────────────────────────────────────────────────────

class TestSarifStructure:
    def test_schema_and_version(self):
        report = _make_report()
        sarif = _build_sarif_dict(report)
        assert sarif["$schema"] == SARIF_SCHEMA_URI
        assert sarif["version"] == "2.1.0"

    def test_single_run(self):
        report = _make_report()
        sarif = _build_sarif_dict(report)
        assert len(sarif["runs"]) == 1

    def test_tool_driver(self):
        report = _make_report()
        sarif = _build_sarif_dict(report)
        driver = sarif["runs"][0]["tool"]["driver"]
        assert driver["name"] == "CodeAudit"
        assert "version" in driver
        assert "rules" in driver

    def test_results_count(self):
        findings = [
            _make_finding(title="A", severity=Severity.IMPORTANT),
            _make_finding(title="B", severity=Severity.NIT),
            _make_finding(title="C", severity=Severity.PRE_EXISTING),
        ]
        report = _make_report(findings)
        sarif = _build_sarif_dict(report)
        assert len(sarif["runs"][0]["results"]) == 3

    def test_invocation_metadata(self):
        report = _make_report()
        sarif = _build_sarif_dict(report)
        invocation = sarif["runs"][0]["invocations"][0]
        assert invocation["executionSuccessful"] is True
        assert invocation["properties"]["auditId"] == "test-audit-123"
        assert invocation["properties"]["mode"] == "deep"


# ── Severity to SARIF level mapping ──────────────────────────────────────

class TestSeverityMapping:
    def test_important_maps_to_error(self):
        assert SEVERITY_TO_SARIF_LEVEL[Severity.IMPORTANT] == "error"

    def test_nit_maps_to_warning(self):
        assert SEVERITY_TO_SARIF_LEVEL[Severity.NIT] == "warning"

    def test_pre_existing_maps_to_note(self):
        assert SEVERITY_TO_SARIF_LEVEL[Severity.PRE_EXISTING] == "note"

    def test_sarif_results_have_correct_levels(self):
        findings = [
            _make_finding(title="A", severity=Severity.IMPORTANT),
            _make_finding(title="B", severity=Severity.NIT),
            _make_finding(title="C", severity=Severity.PRE_EXISTING),
        ]
        report = _make_report(findings)
        sarif = _build_sarif_dict(report)
        results = sarif["runs"][0]["results"]
        levels = [r["level"] for r in results]
        assert levels == ["error", "warning", "note"]


# ── Location / artifact ──────────────────────────────────────────────────

class TestSarifLocations:
    def test_finding_location_produces_artifact(self):
        report = _make_report([_make_finding(file_path="src/main.py", start_line=42)])
        sarif = _build_sarif_dict(report)
        result = sarif["runs"][0]["results"][0]
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/main.py"
        assert loc["region"]["startLine"] == 42

    def test_finding_with_end_line(self):
        report = _make_report([_make_finding(start_line=10, end_line=20)])
        sarif = _build_sarif_dict(report)
        region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 10
        assert region["endLine"] == 20

    def test_finding_without_end_line(self):
        report = _make_report([_make_finding(start_line=5, end_line=None)])
        sarif = _build_sarif_dict(report)
        region = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 5
        assert "endLine" not in region

    def test_suggestion_produces_fix(self):
        report = _make_report([_make_finding(suggestion="Use parameterized queries")])
        sarif = _build_sarif_dict(report)
        result = sarif["runs"][0]["results"][0]
        assert "fixes" in result
        assert result["fixes"][0]["description"]["text"] == "Use parameterized queries"

    def test_no_suggestion_no_fix(self):
        report = _make_report([_make_finding(suggestion=None)])
        sarif = _build_sarif_dict(report)
        result = sarif["runs"][0]["results"][0]
        assert "fixes" not in result


# ── Write to file ─────────────────────────────────────────────────────────

class TestWriteSarif:
    def test_write_creates_file(self, tmp_path):
        report = _make_report()
        out = tmp_path / "output" / "results.sarif"
        write_sarif(report, out)
        assert out.is_file()

    def test_written_file_is_valid_json(self, tmp_path):
        report = _make_report()
        out = tmp_path / "results.sarif"
        write_sarif(report, out)
        data = json.loads(out.read_text())
        assert data["version"] == "2.1.0"
        assert len(data["runs"][0]["results"]) == 1

    def test_rules_deduplication(self):
        """Multiple findings with same dimension should produce one rule."""
        findings = [
            _make_finding(title="A", dimension="security"),
            _make_finding(title="B", dimension="security"),
            _make_finding(title="C", dimension="performance"),
        ]
        report = _make_report(findings)
        sarif = _build_sarif_dict(report)
        rules = sarif["runs"][0]["tool"]["driver"]["rules"]
        assert len(rules) == 2
        rule_ids = [r["id"] for r in rules]
        assert "code-audit/security" in rule_ids
        assert "code-audit/performance" in rule_ids
