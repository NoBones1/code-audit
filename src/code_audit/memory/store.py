"""Project memory store — persists review history, team patterns, and codebase knowledge.

Stored in .code-audit/memory/ as JSON files for portability and inspectability.
No external database required.

Memory types:
1. decisions.json — accepted/dismissed findings (what the team considers important)
2. patterns.json — recurring code patterns and their team assessment
3. conventions.json — learned naming, style, and architectural conventions
4. audit_history.json — summary of past audits for trend tracking
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ReviewDecision(BaseModel):
    """A team's decision on a specific finding."""

    finding_title: str
    finding_dimension: str
    finding_tags: list[str] = Field(default_factory=list)
    file_pattern: str = ""  # e.g., "src/api/*.py" or exact path
    action: str  # "accepted" | "dismissed" | "fixed"
    reason: str = ""  # Why it was dismissed (team's explanation)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    audit_id: str = ""

    @property
    def is_dismissal(self) -> bool:
        return self.action == "dismissed"


class CodePattern(BaseModel):
    """A recurring code pattern the team has assessed."""

    pattern_description: str  # e.g., "f-string SQL queries in admin-only endpoints"
    dimension: str
    team_verdict: str  # "acceptable" | "must_fix" | "context_dependent"
    context: str = ""  # When this pattern is acceptable vs not
    occurrences: int = 1
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AuditSummaryRecord(BaseModel):
    """Summary of a past audit for trend tracking."""

    audit_id: str
    timestamp: str
    mode: str
    files_reviewed: int
    total_findings: int
    important: int
    nit: int
    pre_existing: int
    duration_seconds: float
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    dimensions_run: list[str] = Field(default_factory=list)


class ProjectMemory:
    """Manages the persistent memory for a project.

    All data stored in .code-audit/memory/ as JSON files.
    """

    def __init__(self, project_path: Path, memory_dir: str = ".code-audit/memory"):
        self.memory_path = project_path / memory_dir
        self.memory_path.mkdir(parents=True, exist_ok=True)

    # ── Decisions ──────────────────────────────────────────────────

    @property
    def _decisions_path(self) -> Path:
        return self.memory_path / "decisions.json"

    def load_decisions(self) -> list[ReviewDecision]:
        """Load all review decisions."""
        if not self._decisions_path.is_file():
            return []
        data = json.loads(self._decisions_path.read_text())
        return [ReviewDecision(**d) for d in data]

    def save_decision(self, decision: ReviewDecision) -> None:
        """Append a new review decision."""
        decisions = self.load_decisions()
        decisions.append(decision)
        self._write_json(self._decisions_path, [d.model_dump() for d in decisions])

    def get_dismissals(self) -> list[ReviewDecision]:
        """Get all dismissed findings — used to suppress future false positives."""
        return [d for d in self.load_decisions() if d.is_dismissal]

    def get_dismissal_patterns(self) -> list[str]:
        """Extract dismissal patterns as natural language for prompt injection.

        Returns lines like:
        - "Team dismissed 'f-string SQL in admin endpoints' in src/admin/ — reason: admin-only, no user input"
        """
        dismissals = self.get_dismissals()
        if not dismissals:
            return []

        patterns: list[str] = []
        for d in dismissals:
            line = f"Team dismissed '{d.finding_title}' ({d.finding_dimension})"
            if d.file_pattern:
                line += f" in {d.file_pattern}"
            if d.reason:
                line += f" — reason: {d.reason}"
            patterns.append(line)

        return patterns

    # ── Patterns ───────────────────────────────────────────────────

    @property
    def _patterns_path(self) -> Path:
        return self.memory_path / "patterns.json"

    def load_patterns(self) -> list[CodePattern]:
        """Load all known code patterns."""
        if not self._patterns_path.is_file():
            return []
        data = json.loads(self._patterns_path.read_text())
        return [CodePattern(**p) for p in data]

    def save_pattern(self, pattern: CodePattern) -> None:
        """Add or update a code pattern."""
        patterns = self.load_patterns()
        # Update existing pattern if title matches
        for i, existing in enumerate(patterns):
            if existing.pattern_description == pattern.pattern_description:
                pattern.occurrences = existing.occurrences + 1
                patterns[i] = pattern
                self._write_json(self._patterns_path, [p.model_dump() for p in patterns])
                return
        patterns.append(pattern)
        self._write_json(self._patterns_path, [p.model_dump() for p in patterns])

    def get_acceptable_patterns(self) -> list[str]:
        """Get patterns the team considers acceptable — for prompt injection."""
        patterns = self.load_patterns()
        acceptable = [p for p in patterns if p.team_verdict == "acceptable"]
        if not acceptable:
            return []
        return [
            f"Acceptable pattern: '{p.pattern_description}' ({p.dimension})"
            + (f" — context: {p.context}" if p.context else "")
            for p in acceptable
        ]

    # ── Audit History ──────────────────────────────────────────────

    @property
    def _history_path(self) -> Path:
        return self.memory_path / "audit_history.json"

    def load_history(self) -> list[AuditSummaryRecord]:
        """Load audit history."""
        if not self._history_path.is_file():
            return []
        data = json.loads(self._history_path.read_text())
        return [AuditSummaryRecord(**r) for r in data]

    def save_audit_summary(self, record: AuditSummaryRecord) -> None:
        """Record an audit summary for trend tracking."""
        history = self.load_history()
        history.append(record)
        # Keep last 100 audits
        if len(history) > 100:
            history = history[-100:]
        self._write_json(self._history_path, [r.model_dump() for r in history])

    # ── Memory Prompt Generation ───────────────────────────────────

    def format_for_prompt(self) -> str:
        """Generate a memory context section for injection into agent prompts.

        This is the main integration point — call this and inject the result
        into the agent system prompts.
        """
        sections: list[str] = []

        dismissal_patterns = self.get_dismissal_patterns()
        if dismissal_patterns:
            sections.append("### Team Review History (previously dismissed findings)")
            sections.append("The team has previously reviewed and dismissed these patterns.")
            sections.append("Do NOT flag these again unless the context has materially changed:")
            for p in dismissal_patterns[-20:]:  # Limit to most recent 20
                sections.append(f"- {p}")

        acceptable = self.get_acceptable_patterns()
        if acceptable:
            sections.append("\n### Known Acceptable Patterns")
            sections.append("The team has explicitly marked these patterns as acceptable:")
            for p in acceptable[-15:]:
                sections.append(f"- {p}")

        if not sections:
            return ""

        return "\n".join(sections)

    # ── Utilities ──────────────────────────────────────────────────

    def _write_json(self, path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
