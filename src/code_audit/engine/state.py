"""File-based state management for audit runs.

Manages the .audit/ directory for progress tracking and resumability.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from code_audit.models.finding import Finding
from code_audit.models.report import AuditReport


class AuditState:
    """Manages the .audit/ directory for an audit run."""

    def __init__(self, project_path: Path, output_dir: str = ".audit"):
        self.audit_dir = project_path / output_dir
        self.findings_dir = self.audit_dir / "findings"

    def initialize(self, audit_id: str, config_snapshot: dict) -> None:
        """Initialize the audit directory for a new run."""
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.findings_dir.mkdir(parents=True, exist_ok=True)

        # Write frozen config
        config_path = self.audit_dir / "config.json"
        config_path.write_text(json.dumps(config_snapshot, indent=2, default=str))

        # Initialize progress
        self._write_progress({
            "audit_id": audit_id,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "agents": {},
        })

    def update_agent_status(
        self,
        agent_name: str,
        status: str,
        finding_count: int = 0,
        duration: float = 0.0,
    ) -> None:
        """Update the status of a specific agent."""
        progress = self._read_progress()
        progress["agents"][agent_name] = {
            "status": status,
            "finding_count": finding_count,
            "duration_seconds": round(duration, 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_progress(progress)

    def save_agent_findings(self, agent_name: str, findings: list[Finding]) -> None:
        """Save findings from a specific agent to disk."""
        findings_path = self.findings_dir / f"{agent_name}.json"
        data = [f.model_dump(mode="json") for f in findings]
        findings_path.write_text(json.dumps(data, indent=2))

    def save_report(self, report: AuditReport) -> None:
        """Save the final audit report."""
        report_path = self.audit_dir / "report.json"
        report_path.write_text(report.model_dump_json(indent=2))

    def mark_completed(self, total_findings: int, duration: float) -> None:
        """Mark the audit as completed."""
        progress = self._read_progress()
        progress["status"] = "completed"
        progress["completed_at"] = datetime.now(timezone.utc).isoformat()
        progress["total_findings"] = total_findings
        progress["total_duration_seconds"] = round(duration, 2)
        self._write_progress(progress)

    def mark_failed(self, error: str) -> None:
        """Mark the audit as failed."""
        progress = self._read_progress()
        progress["status"] = "failed"
        progress["error"] = error
        progress["failed_at"] = datetime.now(timezone.utc).isoformat()
        self._write_progress(progress)

    def _read_progress(self) -> dict:
        progress_path = self.audit_dir / "progress.json"
        if progress_path.is_file():
            return json.loads(progress_path.read_text())
        return {}

    def _write_progress(self, data: dict) -> None:
        progress_path = self.audit_dir / "progress.json"
        progress_path.write_text(json.dumps(data, indent=2))
