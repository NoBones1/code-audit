"""Base review agent -- handles prompt assembly, LLM invocation, response parsing."""

from __future__ import annotations

import time
from pathlib import Path

from code_audit.llm.provider import LLMProvider
from code_audit.models.agent_response import AgentFindingsResponse
from code_audit.models.context import ReviewContext
from code_audit.models.finding import Finding


# Directory containing prompt template files
PROMPTS_DIR = Path(__file__).parent / "prompts"


class BaseReviewAgent:
    """Base class for all specialist review agents.

    Each agent has:
    - A dimension name (security, architectural, etc.)
    - A system prompt loaded from a .md file
    - An LLM provider for making API calls
    """

    dimension: str = ""  # Override in subclasses
    prompt_file: str = ""  # Override in subclasses

    def __init__(self, llm: LLMProvider, extra_instructions: str | None = None):
        self.llm = llm
        self.extra_instructions = extra_instructions
        self._system_prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the system prompt template from the .md file."""
        prompt_path = PROMPTS_DIR / self.prompt_file
        if not prompt_path.is_file():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def build_system_prompt(self, context: ReviewContext) -> str:
        """Assemble the full system prompt with injected context."""
        prompt = self._system_prompt_template

        # Inject codebase context
        prompt = prompt.replace("{{CODEBASE_CONTEXT}}", context.summary_for_prompt())

        # Inject review rules
        rules_text = ""
        if context.review_rules:
            rules_text = context.review_rules.format_for_prompt()
        prompt = prompt.replace("{{REVIEW_RULES}}", rules_text or "No specific review rules defined.")

        # Inject project context (CLAUDE.md)
        project_ctx = context.project_context or "No project context file (CLAUDE.md) found."
        prompt = prompt.replace("{{PROJECT_CONTEXT}}", project_ctx)

        # Append extra instructions if provided
        if self.extra_instructions:
            prompt += f"\n\n## Additional Instructions\n{self.extra_instructions}"

        return prompt

    def build_user_prompt(self, context: ReviewContext) -> str:
        """Build the user prompt containing the actual code to review."""
        parts: list[str] = []
        parts.append("# Code Changes to Review\n")

        for diff in context.diffs:
            if diff.is_binary:
                parts.append(f"## {diff.file_path} [binary file — skipped]")
                continue

            parts.append(f"## {diff.file_path}")
            if diff.language:
                parts.append(f"Language: {diff.language}")
            parts.append(f"Status: {diff.status} (+{diff.additions}/-{diff.deletions})")
            parts.append("")

            # Include full file content if available
            if diff.file_path in context.changed_files:
                parts.append("### Full file content:")
                parts.append(f"```{diff.language or ''}")
                parts.append(context.changed_files[diff.file_path])
                parts.append("```")
                parts.append("")

            # Always include the diff
            parts.append("### Diff:")
            parts.append("```diff")
            parts.append(diff.raw_diff)
            parts.append("```")
            parts.append("")

        return "\n".join(parts)

    async def review(self, context: ReviewContext) -> tuple[list[Finding], str, float]:
        """Execute the review and return (findings, summary, duration_seconds).

        This is the main entry point for running a review agent.
        """
        start = time.monotonic()

        system_prompt = self.build_system_prompt(context)
        user_prompt = self.build_user_prompt(context)

        response = await self.llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=AgentFindingsResponse,
            temperature=0.2,
            max_tokens=8192,
        )

        # Convert agent findings to full Finding objects
        findings = [f.to_finding(self.dimension) for f in response.findings]

        duration = time.monotonic() - start
        return findings, response.summary, duration
