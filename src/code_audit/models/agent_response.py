"""Structured response schema for LLM agents.

This model is passed to the LLM via structured output (Claude's messages.parse()
or Gemini's response_json_schema) to guarantee valid JSON responses.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from code_audit.models.finding import Finding


class AgentFindingsResponse(BaseModel):
    """Schema for structured LLM output from review agents.

    This is the exact schema passed to the LLM -- it must be clean and
    self-descriptive so the model understands what to produce.
    """

    findings: list[AgentFinding] = Field(
        description="List of issues found. Empty list if no issues detected.",
    )
    summary: str = Field(
        description="1-2 sentence summary of your assessment of the reviewed code.",
    )
    files_reviewed: list[str] = Field(
        description="List of file paths you analyzed.",
    )


class AgentFinding(BaseModel):
    """A single finding as reported by a specialist agent.

    This is a slightly simpler schema than the full Finding model --
    the orchestrator enriches it with dimension, id, and related_findings.
    """

    severity: str = Field(
        description="One of: important, nit, pre_existing",
    )
    title: str = Field(
        max_length=120,
        description="Short description of the issue (max 120 chars)",
    )
    description: str = Field(
        description="Detailed explanation of why this is a problem (2-4 sentences)",
    )
    file_path: str = Field(
        description="Relative file path from project root",
    )
    start_line: int = Field(
        ge=1,
        description="Line number where the issue starts",
    )
    end_line: int | None = Field(
        default=None,
        description="Line number where the issue ends (null if single line)",
    )
    snippet: str = Field(
        description="The relevant code snippet containing the issue",
    )
    suggestion: str | None = Field(
        default=None,
        description="Suggested fix -- either a code replacement or a description of what to change",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Your confidence that this is a real issue (0.0 = uncertain, 1.0 = certain)",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Relevant tags, e.g. owasp-a01, n+1-query, solid-violation",
    )
    dimension: str = Field(
        default="combined",
        description="Which audit dimension produced this finding (security, architectural, etc.)",
    )

    def to_finding(self, dimension: str | None = None) -> Finding:
        """Convert agent finding to full Finding model.

        Args:
            dimension: Override dimension. If None, uses self.dimension.
        """
        from code_audit.models.finding import FindingLocation, Severity

        severity_map = {
            "important": Severity.IMPORTANT,
            "nit": Severity.NIT,
            "pre_existing": Severity.PRE_EXISTING,
        }

        effective_dimension = dimension or self.dimension

        return Finding(
            dimension=effective_dimension,
            severity=severity_map.get(self.severity.lower(), Severity.NIT),
            title=self.title,
            description=self.description,
            location=FindingLocation(
                file_path=self.file_path,
                start_line=self.start_line,
                end_line=self.end_line,
                snippet=self.snippet,
            ),
            suggestion=self.suggestion,
            confidence=self.confidence,
            tags=self.tags,
        )


# Fix forward reference -- AgentFindingsResponse references AgentFinding
AgentFindingsResponse.model_rebuild()
