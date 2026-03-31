"""Combined agent for quick mode -- reviews all dimensions in a single pass."""

from code_audit.agents.base import BaseReviewAgent


class CombinedAgent(BaseReviewAgent):
    dimension = "combined"
    prompt_file = "combined.md"
