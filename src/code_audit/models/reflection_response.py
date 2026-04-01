"""Response model for agent self-reflection."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ReflectionAction(str, Enum):
    KEEP = "keep"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    WITHDRAW = "withdraw"


class FindingReflection(BaseModel):
    """Reflection on a single finding."""
    finding_id: str = Field(description="ID of the finding being reflected on")
    action: ReflectionAction = Field(description="Action to take on this finding")
    new_confidence: float | None = Field(
        default=None,
        description="New confidence score (only for UPGRADE/DOWNGRADE)",
        ge=0.0, le=1.0,
    )
    cross_references: list[str] = Field(
        default_factory=list,
        description="IDs of related findings from other agents",
    )
    reason: str = Field(
        default="",
        description="Brief explanation for the action",
    )


class ReflectionResponse(BaseModel):
    """Response from a reflection agent."""
    reflections: list[FindingReflection] = Field(default_factory=list)
    summary: str = Field(default="", description="Brief summary of reflection changes")
