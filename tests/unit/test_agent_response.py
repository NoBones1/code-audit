"""Unit tests for AgentFinding.to_finding() and severity mapping."""

import pytest

from code_audit.models.agent_response import AgentFinding, AgentFindingsResponse
from code_audit.models.finding import Severity


def _make_agent_finding(
    severity: str = "important",
    title: str = "Test issue",
    dimension: str = "security",
) -> AgentFinding:
    return AgentFinding(
        severity=severity,
        title=title,
        description="Detailed issue description.",
        file_path="src/app.py",
        start_line=10,
        snippet="bad_code()",
        confidence=0.9,
        dimension=dimension,
    )


# ── Severity mapping ─────────────────────────────────────────────────────

class TestSeverityMapping:
    @pytest.mark.parametrize("raw,expected", [
        ("important", Severity.IMPORTANT),
        ("Important", Severity.IMPORTANT),
        ("IMPORTANT", Severity.IMPORTANT),
        ("nit", Severity.NIT),
        ("Nit", Severity.NIT),
        ("NIT", Severity.NIT),
        ("pre_existing", Severity.PRE_EXISTING),
        ("Pre_Existing", Severity.PRE_EXISTING),
        ("PRE_EXISTING", Severity.PRE_EXISTING),
    ])
    def test_case_insensitive_severity(self, raw, expected):
        af = _make_agent_finding(severity=raw)
        finding = af.to_finding()
        assert finding.severity == expected

    def test_unknown_severity_defaults_to_nit(self):
        af = _make_agent_finding(severity="critical")
        finding = af.to_finding()
        assert finding.severity == Severity.NIT

    def test_empty_severity_defaults_to_nit(self):
        af = _make_agent_finding(severity="unknown_value")
        finding = af.to_finding()
        assert finding.severity == Severity.NIT


# ── Dimension handling ────────────────────────────────────────────────────

class TestDimensionHandling:
    def test_explicit_dimension_overrides(self):
        af = _make_agent_finding(dimension="combined")
        finding = af.to_finding(dimension="security")
        assert finding.dimension == "security"

    def test_none_dimension_uses_self(self):
        af = _make_agent_finding(dimension="architectural")
        finding = af.to_finding(dimension=None)
        assert finding.dimension == "architectural"

    def test_no_dimension_param_uses_self(self):
        af = _make_agent_finding(dimension="performance")
        finding = af.to_finding()
        assert finding.dimension == "performance"

    def test_default_dimension_is_combined(self):
        af = AgentFinding(
            severity="nit",
            title="Test",
            description="Desc",
            file_path="f.py",
            start_line=1,
            snippet="code",
            confidence=0.5,
            # dimension not set — defaults to "combined"
        )
        finding = af.to_finding()
        assert finding.dimension == "combined"


# ── to_finding() field mapping ────────────────────────────────────────────

class TestToFinding:
    def test_basic_fields_mapped(self):
        af = _make_agent_finding(title="SQL injection")
        finding = af.to_finding()
        assert finding.title == "SQL injection"
        assert finding.description == "Detailed issue description."
        assert finding.confidence == 0.9
        assert finding.location.file_path == "src/app.py"
        assert finding.location.start_line == 10
        assert finding.location.snippet == "bad_code()"

    def test_end_line_mapped(self):
        af = AgentFinding(
            severity="nit",
            title="Multi-line issue",
            description="Spans lines",
            file_path="app.py",
            start_line=5,
            end_line=15,
            snippet="code block",
            confidence=0.7,
        )
        finding = af.to_finding()
        assert finding.location.end_line == 15

    def test_suggestion_mapped(self):
        af = AgentFinding(
            severity="important",
            title="Issue",
            description="Desc",
            file_path="f.py",
            start_line=1,
            snippet="code",
            suggestion="Use X instead",
            confidence=0.8,
        )
        finding = af.to_finding()
        assert finding.suggestion == "Use X instead"

    def test_tags_mapped(self):
        af = AgentFinding(
            severity="nit",
            title="Issue",
            description="Desc",
            file_path="f.py",
            start_line=1,
            snippet="code",
            confidence=0.5,
            tags=["owasp-a01", "cwe-89"],
        )
        finding = af.to_finding()
        assert finding.tags == ["owasp-a01", "cwe-89"]

    def test_finding_has_id(self):
        af = _make_agent_finding()
        finding = af.to_finding()
        assert finding.id  # Should have auto-generated id
        assert len(finding.id) == 12  # hex[:12]


# ── AgentFindingsResponse ────────────────────────────────────────────────

class TestAgentFindingsResponse:
    def test_empty_findings_valid(self):
        resp = AgentFindingsResponse(
            findings=[],
            summary="No issues found.",
            files_reviewed=["app.py"],
        )
        assert len(resp.findings) == 0

    def test_response_with_findings(self):
        resp = AgentFindingsResponse(
            findings=[_make_agent_finding()],
            summary="Found 1 issue.",
            files_reviewed=["src/app.py"],
        )
        assert len(resp.findings) == 1
        assert resp.summary == "Found 1 issue."
