"""Review decision tracking — records team responses to findings.

When a developer accepts, fixes, or dismisses a finding, this module
records that decision so future reviews can learn from it.
"""

from __future__ import annotations

from pathlib import Path

from code_audit.memory.store import (
    AuditSummaryRecord,
    CodePattern,
    ProjectMemory,
    ReviewDecision,
)
from code_audit.models.finding import Finding
from code_audit.models.report import AuditReport


class DecisionTracker:
    """Tracks team decisions on findings and updates project memory."""

    def __init__(self, project_path: Path):
        self.memory = ProjectMemory(project_path)

    def record_dismissal(
        self,
        finding: Finding,
        reason: str = "",
        audit_id: str = "",
    ) -> None:
        """Record that a finding was dismissed by the team."""
        self.memory.save_decision(ReviewDecision(
            finding_title=finding.title,
            finding_dimension=finding.dimension,
            finding_tags=finding.tags,
            file_pattern=finding.location.file_path,
            action="dismissed",
            reason=reason,
            audit_id=audit_id,
        ))

    def record_acceptance(
        self,
        finding: Finding,
        audit_id: str = "",
    ) -> None:
        """Record that a finding was accepted / fix was applied."""
        self.memory.save_decision(ReviewDecision(
            finding_title=finding.title,
            finding_dimension=finding.dimension,
            finding_tags=finding.tags,
            file_pattern=finding.location.file_path,
            action="accepted",
            audit_id=audit_id,
        ))

    def record_pattern(
        self,
        description: str,
        dimension: str,
        verdict: str,
        context: str = "",
    ) -> None:
        """Record a code pattern assessment.

        Args:
            description: What the pattern is
            dimension: Which audit dimension it relates to
            verdict: "acceptable" | "must_fix" | "context_dependent"
            context: When this pattern is/isn't acceptable
        """
        self.memory.save_pattern(CodePattern(
            pattern_description=description,
            dimension=dimension,
            team_verdict=verdict,
            context=context,
        ))

    def record_audit_completion(self, report: AuditReport) -> None:
        """Record an audit completion for trend tracking."""
        self.memory.save_audit_summary(AuditSummaryRecord(
            audit_id=report.audit_id,
            timestamp=report.timestamp.isoformat(),
            mode=report.mode,
            files_reviewed=report.summary.files_reviewed,
            total_findings=report.summary.total_findings,
            important=report.summary.important,
            nit=report.summary.nit,
            pre_existing=report.summary.pre_existing,
            duration_seconds=report.duration_seconds,
            dimensions_run=report.summary.dimensions_run,
        ))

    def should_suppress(self, finding: Finding) -> bool:
        """Check if a finding should be suppressed based on prior dismissals.

        A finding is suppressed if:
        1. A finding with the same title was previously dismissed
        2. AND it was for the same file pattern or a broader pattern
        3. AND it was dismissed recently (within last 50 decisions)
        """
        dismissals = self.memory.get_dismissals()
        if not dismissals:
            return False

        # Check recent dismissals (last 50)
        recent = dismissals[-50:]
        for d in recent:
            # Match on title (exact or substring)
            title_match = (
                d.finding_title.lower() == finding.title.lower()
                or d.finding_title.lower() in finding.title.lower()
                or finding.title.lower() in d.finding_title.lower()
            )
            if not title_match:
                continue

            # Match on dimension
            if d.finding_dimension != finding.dimension:
                continue

            # Match on file pattern
            if d.file_pattern:
                # Exact file match or glob-like prefix match
                if (finding.location.file_path == d.file_pattern
                        or finding.location.file_path.startswith(
                            d.file_pattern.rstrip("*").rstrip("/")
                        )):
                    return True
            else:
                # No file pattern = global dismissal for this finding type
                return True

        return False
