"""Review context models -- the input bundle sent to each agent."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HunkDiff(BaseModel):
    """A single hunk within a file diff."""

    header: str = Field(description="The @@ line showing line ranges")
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str = Field(description="The diff content with +/- prefixes")


class FileDiff(BaseModel):
    """Structured representation of a single file's diff."""

    file_path: str
    old_path: str | None = None  # For renames
    status: str = Field(description="added | modified | deleted | renamed")
    hunks: list[HunkDiff] = Field(default_factory=list)
    is_binary: bool = False
    language: str | None = None  # Detected from extension
    additions: int = 0
    deletions: int = 0

    @property
    def total_changes(self) -> int:
        return self.additions + self.deletions

    @property
    def raw_diff(self) -> str:
        """Reconstruct the raw diff text from hunks."""
        parts = [f"--- a/{self.old_path or self.file_path}", f"+++ b/{self.file_path}"]
        for hunk in self.hunks:
            parts.append(hunk.header)
            parts.append(hunk.content)
        return "\n".join(parts)


class ReviewRules(BaseModel):
    """Parsed rules from REVIEW.md."""

    mandatory_checks: list[str] = Field(
        default_factory=list,
        description="Rules that MUST be checked (from '## Always check')",
    )
    style_rules: list[str] = Field(
        default_factory=list,
        description="Style preferences to enforce (from '## Style')",
    )
    skip_rules: list[str] = Field(
        default_factory=list,
        description="Patterns/areas to skip (from '## Skip')",
    )

    @property
    def has_rules(self) -> bool:
        return bool(self.mandatory_checks or self.style_rules or self.skip_rules)

    def format_for_prompt(self) -> str:
        """Format rules for injection into agent system prompts."""
        sections = []
        if self.mandatory_checks:
            sections.append("### Mandatory Checks (MUST verify)")
            for rule in self.mandatory_checks:
                sections.append(f"- {rule}")
        if self.style_rules:
            sections.append("\n### Style Rules (enforce these conventions)")
            for rule in self.style_rules:
                sections.append(f"- {rule}")
        if self.skip_rules:
            sections.append("\n### Skip Rules (do NOT flag issues matching these)")
            for rule in self.skip_rules:
                sections.append(f"- {rule}")
        return "\n".join(sections)


class ReviewContext(BaseModel):
    """Complete context bundle sent to review agents."""

    target_path: str = Field(description="Absolute path to project root")
    languages: list[str] = Field(default_factory=list, description="Detected languages")
    frameworks: list[str] = Field(default_factory=list, description="Detected frameworks")
    file_tree: str = Field(default="", description="Simplified directory structure")
    diffs: list[FileDiff] = Field(default_factory=list, description="Structured file diffs")
    changed_files: dict[str, str] = Field(
        default_factory=dict,
        description="file_path → full file content for heavily changed files",
    )
    review_rules: ReviewRules | None = None
    project_context: str | None = Field(
        default=None,
        description="CLAUDE.md contents if present",
    )
    diff_target: str = Field(
        default="HEAD",
        description="What we're diffing against (branch, commit, HEAD)",
    )
    total_additions: int = 0
    total_deletions: int = 0

    @property
    def total_changes(self) -> int:
        return self.total_additions + self.total_deletions

    @property
    def changed_file_paths(self) -> list[str]:
        return [d.file_path for d in self.diffs]

    def summary_for_prompt(self) -> str:
        """Generate a concise context summary for agent prompts."""
        lines = [
            f"Languages: {', '.join(self.languages) if self.languages else 'unknown'}",
            f"Frameworks: {', '.join(self.frameworks) if self.frameworks else 'none detected'}",
            f"Files changed: {len(self.diffs)}",
            f"Total changes: +{self.total_additions} / -{self.total_deletions}",
        ]
        if self.file_tree:
            lines.append(f"\nProject structure:\n{self.file_tree}")
        return "\n".join(lines)
