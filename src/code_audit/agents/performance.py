"""Performance & Efficiency specialist agent."""

from code_audit.agents.base import BaseReviewAgent


class PerformanceAgent(BaseReviewAgent):
    dimension = "performance"
    prompt_file = "performance.md"
