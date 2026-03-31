"""Security & Compliance specialist agent."""

from code_audit.agents.base import BaseReviewAgent


class SecurityAgent(BaseReviewAgent):
    dimension = "security"
    prompt_file = "security.md"
