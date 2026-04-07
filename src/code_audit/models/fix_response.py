"""Structured response schema for the fix-generation LLM call."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FixResult(BaseModel):
    """The LLM's concrete code replacement for a finding."""

    replacement_code: str = Field(
        description="The corrected code to replace the original snippet. "
        "Must preserve the original indentation style.",
    )
    explanation: str = Field(
        description="One sentence explaining what was changed and why.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence that this fix is correct and safe to apply.",
    )
