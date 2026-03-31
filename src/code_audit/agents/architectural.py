"""Architectural Integrity specialist agent."""

from code_audit.agents.base import BaseReviewAgent


class ArchitecturalAgent(BaseReviewAgent):
    dimension = "architectural"
    prompt_file = "architectural.md"
