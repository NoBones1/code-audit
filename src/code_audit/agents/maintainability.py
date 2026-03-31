"""Maintainability specialist agent."""

from code_audit.agents.base import BaseReviewAgent


class MaintainabilityAgent(BaseReviewAgent):
    dimension = "maintainability"
    prompt_file = "maintainability.md"
