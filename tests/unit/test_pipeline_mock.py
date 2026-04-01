"""End-to-end pipeline test with mocked LLM responses."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from code_audit.config.models import AuditConfig, ReviewMode
from code_audit.engine.orchestrator import Orchestrator
from code_audit.models.agent_response import AgentFinding, AgentFindingsResponse
from code_audit.models.finding import Severity
from code_audit.output.markdown import render_markdown_report
from code_audit.output.sarif_writer import write_sarif


# Mock LLM response for the combined agent
MOCK_RESPONSE = AgentFindingsResponse(
    findings=[
        AgentFinding(
            severity="important",
            title="SQL injection vulnerability",
            description="User input is passed directly to SQL query via f-string interpolation. An attacker can inject arbitrary SQL.",
            file_path="app.py",
            start_line=8,
            snippet='cursor.execute(f"SELECT * FROM users WHERE id = {user_id} OR 1=1")',
            suggestion="Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
            confidence=0.95,
            tags=["owasp-a01", "cwe-89"],
        ),
        AgentFinding(
            severity="important",
            title="Hardcoded secret exposed",
            description="API key and database password are hardcoded in source code. These will be committed to version control.",
            file_path="app.py",
            start_line=28,
            snippet='API_KEY = "sk-secret-key-12345"\nDB_PASSWORD = "admin123"',
            suggestion="Use environment variables: API_KEY = os.environ.get('API_KEY')",
            confidence=0.98,
            tags=["cwe-798", "secret-exposure"],
        ),
        AgentFinding(
            severity="nit",
            title="Missing request timeout",
            description="HTTP request has no timeout set. This could cause the function to hang indefinitely.",
            file_path="app.py",
            start_line=37,
            snippet="response = requests.get(url)  # No timeout",
            suggestion="Add a timeout: requests.get(url, timeout=30)",
            confidence=0.85,
            tags=["reliability"],
        ),
    ],
    summary="Found 2 critical security issues (SQL injection and hardcoded secrets) and 1 reliability concern.",
    files_reviewed=["app.py"],
)


def test_full_pipeline_with_mock():
    """Test the complete pipeline from diff to report using mocked LLM."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)

        # Set up a git repo with changes
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)

        # Initial file
        (project / "app.py").write_text("print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=project, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=project, check=True)

        # Modified file with bugs
        (project / "app.py").write_text(
            'import sqlite3\n'
            'def get_user(uid):\n'
            '    conn = sqlite3.connect("db")\n'
            '    conn.execute(f"SELECT * FROM users WHERE id={uid}")\n'
            'API_KEY = "secret-123"\n'
        )

        config = AuditConfig()
        config.review.mode = ReviewMode.QUICK

        # Create a mock provider that returns our fixed response
        mock_provider = MagicMock()
        mock_provider.model_name = "mock-model"
        mock_provider.provider_name = "mock"
        mock_provider.complete_structured = AsyncMock(return_value=MOCK_RESPONSE)

        with patch("code_audit.engine.orchestrator.FallbackProvider", return_value=mock_provider):
            orchestrator = Orchestrator(config=config, project_path=project)
            report = asyncio.run(orchestrator.run())

        # Verify report structure
        assert report.audit_id
        assert report.mode == "quick"
        assert len(report.findings) == 3
        assert report.summary.important == 2
        assert report.summary.nit == 1
        assert report.summary.files_reviewed == 1
        assert report.has_important_findings

        # Verify finding details
        sql_finding = next(f for f in report.findings if "SQL" in f.title)
        assert sql_finding.severity == Severity.IMPORTANT
        assert sql_finding.confidence == 0.95
        assert sql_finding.location.file_path == "app.py"
        assert "owasp-a01" in sql_finding.tags

        # Test markdown output
        md = render_markdown_report(report)
        assert "SQL injection" in md
        assert "🔴" in md
        assert "🟡" in md

        # Test SARIF output
        sarif_path = project / ".audit" / "results.sarif"
        write_sarif(report, sarif_path)
        assert sarif_path.is_file()

        sarif_data = json.loads(sarif_path.read_text())
        assert sarif_data["version"] == "2.1.0"
        assert len(sarif_data["runs"]) == 1
        assert len(sarif_data["runs"][0]["results"]) == 3

        # Verify SARIF severity mapping
        results = sarif_data["runs"][0]["results"]
        error_results = [r for r in results if r["level"] == "error"]
        warning_results = [r for r in results if r["level"] == "warning"]
        assert len(error_results) == 2  # 2 important findings
        assert len(warning_results) == 1  # 1 nit finding

        print("All assertions passed!")
        print(f"Report: {report.summary.total_findings} findings in {report.duration_seconds:.1f}s")
        print(f"Markdown length: {len(md)} chars")
        print(f"SARIF file: {sarif_path}")


if __name__ == "__main__":
    test_full_pipeline_with_mock()
