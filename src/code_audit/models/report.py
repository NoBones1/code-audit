"""Audit report model -- the final aggregated output."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from code_audit.models.finding import Dimension, Finding, Severity
from code_audit.models.usage import UsageRecord


class DimensionSummary(BaseModel):
    """Summary stats for a single audit dimension."""

    dimension: str
    total_findings: int = 0
    important: int = 0
    nit: int = 0
    pre_existing: int = 0
    agent_model: str = ""
    duration_seconds: float = 0.0
    avg_confidence: float = 0.0


class AuditSummary(BaseModel):
    """High-level summary of the entire audit."""

    total_findings: int = 0
    important: int = 0
    nit: int = 0
    pre_existing: int = 0
    files_reviewed: int = 0
    dimensions_run: list[str] = Field(default_factory=list)
    dimension_summaries: list[DimensionSummary] = Field(default_factory=list)
    avg_confidence: float = 0.0
    high_confidence_count: int = 0   # findings with confidence > 0.8
    low_confidence_count: int = 0    # findings with confidence < 0.5

    @classmethod
    def from_findings(
        cls,
        findings: list[Finding],
        files_reviewed: int,
        dimensions: list[str],
        dimension_details: list[DimensionSummary] | None = None,
    ) -> AuditSummary:
        important = sum(1 for f in findings if f.severity == Severity.IMPORTANT)
        nit = sum(1 for f in findings if f.severity == Severity.NIT)
        pre_existing = sum(1 for f in findings if f.severity == Severity.PRE_EXISTING)
        avg_confidence = (
            sum(f.confidence for f in findings) / len(findings) if findings else 0.0
        )
        high_confidence_count = sum(1 for f in findings if f.confidence > 0.8)
        low_confidence_count = sum(1 for f in findings if f.confidence < 0.5)
        return cls(
            total_findings=len(findings),
            important=important,
            nit=nit,
            pre_existing=pre_existing,
            files_reviewed=files_reviewed,
            dimensions_run=dimensions,
            dimension_summaries=dimension_details or [],
            avg_confidence=avg_confidence,
            high_confidence_count=high_confidence_count,
            low_confidence_count=low_confidence_count,
        )


class AuditReport(BaseModel):
    """Complete audit report with all findings and metadata."""

    audit_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target_path: str
    mode: str = Field(description="quick | deep | security")
    diff_target: str = "HEAD"
    findings: list[Finding] = Field(default_factory=list)
    summary: AuditSummary = Field(default_factory=AuditSummary)
    duration_seconds: float = 0.0
    review_rules_applied: bool = False
    llm_providers_used: list[str] = Field(default_factory=list)
    usage: list[UsageRecord] = Field(default_factory=list)
    total_cost_usd: float = 0.0

    @property
    def has_important_findings(self) -> bool:
        return self.summary.important > 0

    @property
    def findings_by_severity(self) -> dict[Severity, list[Finding]]:
        result: dict[Severity, list[Finding]] = {s: [] for s in Severity}
        for f in self.findings:
            result[f.severity].append(f)
        return result

    @property
    def findings_by_file(self) -> dict[str, list[Finding]]:
        result: dict[str, list[Finding]] = {}
        for f in self.findings:
            path = f.location.file_path
            if path not in result:
                result[path] = []
            result[path].append(f)
        return result

    @property
    def findings_by_dimension(self) -> dict[str, list[Finding]]:
        result: dict[str, list[Finding]] = {}
        for f in self.findings:
            if f.dimension not in result:
                result[f.dimension] = []
            result[f.dimension].append(f)
        return result
