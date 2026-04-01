"""Agent self-reflection -- cross-agent review to reduce false positives."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from code_audit.llm.provider import LLMProvider
from code_audit.models.finding import Finding
from code_audit.models.reflection_response import ReflectionAction, ReflectionResponse

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "reflection.md"


class ReflectionAgent:
    """Runs one round of self-reflection for a specialist agent."""

    def __init__(self, llm: LLMProvider, dimension: str):
        self.llm = llm
        self.dimension = dimension
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        if PROMPT_PATH.is_file():
            return PROMPT_PATH.read_text(encoding="utf-8")
        # Inline fallback
        return (
            "# Agent Self-Reflection: {{DIMENSION}}\n\n"
            "Review your findings and decide: KEEP, UPGRADE, DOWNGRADE, or WITHDRAW each one.\n\n"
            "## Your Original Findings\n{{OWN_FINDINGS}}\n\n"
            "## All Findings\n{{ALL_FINDINGS}}\n\n"
            "Respond with JSON matching the schema."
        )

    def _format_findings(self, findings: list[Finding]) -> str:
        """Format findings for prompt injection."""
        if not findings:
            return "No findings."
        parts = []
        for f in findings:
            parts.append(
                f"- [{f.id}] ({f.dimension}/{f.severity.value}) {f.title} "
                f"at {f.location.file_path}:{f.location.start_line} "
                f"(confidence: {f.confidence:.0%})"
            )
        return "\n".join(parts)

    async def reflect(
        self,
        own_findings: list[Finding],
        all_findings: list[Finding],
    ) -> tuple[list[Finding], float]:
        """Run reflection and return (updated_findings, duration_seconds).

        Returns the same findings with adjusted confidence and cross-references.
        Withdrawn findings are excluded.
        """
        if not own_findings:
            return [], 0.0

        start = time.monotonic()

        prompt = self._prompt_template
        prompt = prompt.replace("{{DIMENSION}}", self.dimension)
        prompt = prompt.replace("{{OWN_FINDINGS}}", self._format_findings(own_findings))
        prompt = prompt.replace("{{ALL_FINDINGS}}", self._format_findings(all_findings))

        user_prompt = (
            f"Reflect on {len(own_findings)} findings from the {self.dimension} review. "
            f"Total findings across all agents: {len(all_findings)}."
        )

        try:
            response = await self.llm.complete_structured(
                system_prompt=prompt,
                user_prompt=user_prompt,
                response_model=ReflectionResponse,
                temperature=0.1,
                max_tokens=4096,
            )
        except Exception as e:
            logger.warning(f"Reflection failed for {self.dimension}: {e}")
            return own_findings, time.monotonic() - start

        # Apply reflections
        findings_by_id = {f.id: f for f in own_findings}
        updated: list[Finding] = []

        for reflection in response.reflections:
            finding = findings_by_id.pop(reflection.finding_id, None)
            if finding is None:
                continue

            if reflection.action == ReflectionAction.WITHDRAW:
                logger.info(f"Withdrawn: [{finding.id}] {finding.title} -- {reflection.reason}")
                continue

            if reflection.action == ReflectionAction.UPGRADE and reflection.new_confidence is not None:
                finding = finding.model_copy(update={"confidence": min(reflection.new_confidence, 1.0)})
            elif reflection.action == ReflectionAction.DOWNGRADE and reflection.new_confidence is not None:
                finding = finding.model_copy(update={"confidence": max(reflection.new_confidence, 0.1)})

            if reflection.cross_references:
                existing_refs = list(finding.related_findings)
                existing_refs.extend(reflection.cross_references)
                finding = finding.model_copy(update={"related_findings": existing_refs})

            updated.append(finding)

        # Any findings not referenced in reflections are kept as-is
        for remaining in findings_by_id.values():
            updated.append(remaining)

        duration = time.monotonic() - start
        withdrawn_count = len(own_findings) - len(updated)
        if withdrawn_count > 0:
            logger.info(f"{self.dimension} reflection: {withdrawn_count} findings withdrawn")

        return updated, duration
