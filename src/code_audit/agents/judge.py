"""Judge agent -- aggregates, deduplicates, filters, and ranks findings from specialist agents.

The Judge is fundamentally different from specialist agents:
- It receives FINDINGS, not code diffs
- It outputs a filtered/merged set of findings
- Its job is to REDUCE noise, not add to it
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from code_audit.llm.provider import LLMProvider
from code_audit.models.agent_response import AgentFinding, AgentFindingsResponse
from code_audit.models.context import ReviewRules
from code_audit.models.finding import Finding

JUDGE_PROMPT_PATH = Path(__file__).parent / "prompts" / "judge.md"


class JudgeAgent:
    """Aggregates findings from specialist agents into a unified report."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm
        self._system_prompt_template = JUDGE_PROMPT_PATH.read_text(encoding="utf-8")

    def _build_system_prompt(self, review_rules: ReviewRules | None) -> str:
        """Build the judge's system prompt with review rules injected."""
        prompt = self._system_prompt_template
        rules_text = ""
        if review_rules:
            rules_text = review_rules.format_for_prompt()
        prompt = prompt.replace(
            "{{REVIEW_RULES}}",
            rules_text or "No specific skip rules defined.",
        )
        return prompt

    def _format_findings_for_prompt(self, all_findings: list[Finding]) -> str:
        """Format all specialist findings as the user prompt for the judge."""
        parts: list[str] = []
        parts.append("# Specialist Agent Findings\n")
        parts.append(f"Total findings from all agents: {len(all_findings)}\n")

        # Group by dimension
        by_dimension: dict[str, list[Finding]] = {}
        for f in all_findings:
            by_dimension.setdefault(f.dimension, []).append(f)

        for dimension, findings in by_dimension.items():
            parts.append(f"\n## {dimension.upper()} Agent ({len(findings)} findings)\n")
            for f in findings:
                parts.append(f"### Finding: {f.title}")
                parts.append(f"- **ID**: {f.id}")
                parts.append(f"- **Severity**: {f.severity.value}")
                parts.append(f"- **Location**: {f.location.display}")
                parts.append(f"- **Confidence**: {f.confidence}")
                parts.append(f"- **Description**: {f.description}")
                if f.suggestion:
                    parts.append(f"- **Suggestion**: {f.suggestion}")
                if f.tags:
                    parts.append(f"- **Tags**: {', '.join(f.tags)}")
                parts.append(f"- **Snippet**:\n```\n{f.location.snippet}\n```")
                parts.append("")

        return "\n".join(parts)

    async def judge(
        self,
        all_findings: list[Finding],
        review_rules: ReviewRules | None = None,
    ) -> tuple[list[Finding], str, float]:
        """Aggregate, deduplicate, filter, and rank findings.

        Returns (filtered_findings, summary, duration_seconds).
        """
        start = time.monotonic()

        # If very few findings, skip the LLM call and just sort
        if len(all_findings) <= 3:
            sorted_findings = sorted(
                all_findings,
                key=lambda f: (
                    {"important": 0, "nit": 1, "pre_existing": 2}.get(f.severity.value, 3),
                    -f.confidence,
                ),
            )
            duration = time.monotonic() - start
            summary = f"Reviewed {len(all_findings)} findings. All retained (below dedup threshold)."
            return sorted_findings, summary, duration

        system_prompt = self._build_system_prompt(review_rules)
        user_prompt = self._format_findings_for_prompt(all_findings)

        response = await self.llm.complete_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=AgentFindingsResponse,
            temperature=0.1,  # Low temperature for consistent judging
            max_tokens=8192,
        )

        # Convert agent findings to full Finding objects
        judged_findings = [f.to_finding(f.dimension if hasattr(f, 'dimension') else "combined")
                          for f in response.findings]

        # Try to preserve original finding IDs where possible by matching on title+file
        original_by_key: dict[str, Finding] = {}
        for f in all_findings:
            key = f"{f.title}:{f.location.file_path}:{f.location.start_line}"
            original_by_key[key] = f

        for jf in judged_findings:
            key = f"{jf.title}:{jf.location.file_path}:{jf.location.start_line}"
            if key in original_by_key:
                jf.id = original_by_key[key].id

        duration = time.monotonic() - start
        return judged_findings, response.summary, duration
