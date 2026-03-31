"""Functional Correctness specialist agent."""

from code_audit.agents.base import BaseReviewAgent


class FunctionalAgent(BaseReviewAgent):
    dimension = "functional"
    prompt_file = "functional.md"
