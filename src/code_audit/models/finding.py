"""Core finding model -- the fundamental unit of a code audit."""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Finding severity levels matching Claude Code Review conventions."""

    IMPORTANT = "important"  # 🔴 Bug that should be fixed before merging
    NIT = "nit"  # 🟡 Minor issue, worth fixing but not blocking
    PRE_EXISTING = "pre_existing"  # 🟣 Bug not introduced by current changes

    @property
    def emoji(self) -> str:
        return {
            Severity.IMPORTANT: "🔴",
            Severity.NIT: "🟡",
            Severity.PRE_EXISTING: "🟣",
        }[self]

    @property
    def sarif_level(self) -> str:
        """Map to SARIF 2.1.0 level values."""
        return {
            Severity.IMPORTANT: "error",
            Severity.NIT: "warning",
            Severity.PRE_EXISTING: "note",
        }[self]

    @property
    def label(self) -> str:
        return {
            Severity.IMPORTANT: "Important",
            Severity.NIT: "Nit",
            Severity.PRE_EXISTING: "Pre-existing",
        }[self]


class Dimension(str, Enum):
    """The five audit dimensions -- one per specialist agent."""

    SECURITY = "security"
    ARCHITECTURAL = "architectural"
    PERFORMANCE = "performance"
    FUNCTIONAL = "functional"
    MAINTAINABILITY = "maintainability"
    COMBINED = "combined"  # Used in quick mode


class Confidence(float, Enum):
    """Confidence thresholds for finding filtering."""

    HIGH = 0.9
    MEDIUM = 0.7
    LOW = 0.5
    MINIMUM = 0.3  # Below this, the judge should discard


class FindingLocation(BaseModel):
    """Precise location of a finding in the codebase."""

    file_path: str = Field(description="Relative path from project root")
    start_line: int = Field(ge=1, description="First line of the finding")
    end_line: int | None = Field(default=None, ge=1, description="Last line (defaults to start_line)")
    snippet: str = Field(description="The relevant code snippet")

    @property
    def effective_end_line(self) -> int:
        return self.end_line or self.start_line

    @property
    def display(self) -> str:
        if self.end_line and self.end_line != self.start_line:
            return f"{self.file_path}:{self.start_line}-{self.end_line}"
        return f"{self.file_path}:{self.start_line}"


class Finding(BaseModel):
    """A single code review finding from a specialist agent."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    dimension: str = Field(description="Which agent produced this finding")
    severity: Severity
    title: str = Field(max_length=120, description="Short description of the issue")
    description: str = Field(description="Detailed explanation (2-4 sentences)")
    location: FindingLocation
    suggestion: str | None = Field(default=None, description="Suggested fix (code or description)")
    confidence: float = Field(ge=0.0, le=1.0, description="Agent's confidence in this finding")
    tags: list[str] = Field(default_factory=list, description="E.g., owasp-a01, n+1-query")
    related_findings: list[str] = Field(
        default_factory=list,
        description="IDs of related findings (set by judge)",
    )

    @property
    def severity_display(self) -> str:
        return f"{self.severity.emoji} {self.severity.label}"
