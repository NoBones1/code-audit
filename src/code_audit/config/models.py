"""Pydantic configuration models."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class LLMProvider(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"
    OPENAI_COMPAT = "openai_compat"


class ReviewMode(str, Enum):
    QUICK = "quick"
    DEEP = "deep"
    SECURITY = "security"


class OutputFormat(str, Enum):
    TERMINAL = "terminal"
    MARKDOWN = "markdown"
    SARIF = "sarif"


class LLMConfig(BaseModel):
    """Configuration for an LLM provider."""

    provider: LLMProvider = LLMProvider.CLAUDE
    model: str = "claude-sonnet-4-6"
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None  # For openai_compat
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8192, ge=256)


class AgentConfig(BaseModel):
    """Per-agent LLM override configuration."""

    enabled: bool = True
    llm: LLMConfig | None = None  # Override default LLM for this agent
    extra_instructions: str | None = None  # Additional prompt text


class ReviewConfig(BaseModel):
    """Review behavior configuration."""

    mode: ReviewMode = ReviewMode.DEEP
    include: list[str] = Field(default_factory=lambda: ["**/*"])
    exclude: list[str] = Field(
        default_factory=lambda: [
            "**/*.test.*",
            "**/*.spec.*",
            "**/__tests__/**",
            "node_modules/**",
            "dist/**",
            "build/**",
            ".git/**",
            "*.lock",
            "package-lock.json",
            "yarn.lock",
        ]
    )
    max_files: int = Field(default=50, ge=1)
    max_file_size_kb: int = Field(default=500, ge=1)
    diff_target: str = "HEAD"  # Branch, commit, or HEAD


class OutputConfig(BaseModel):
    """Output configuration."""

    formats: list[OutputFormat] = Field(
        default_factory=lambda: [OutputFormat.TERMINAL, OutputFormat.MARKDOWN, OutputFormat.SARIF]
    )
    directory: str = ".audit"
    sarif_file: str = "results.sarif"
    markdown_file: str = "report.md"


class AuditConfig(BaseModel):
    """Root configuration model."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    def llm_for_agent(self, agent_name: str) -> LLMConfig:
        """Get the effective LLM config for a specific agent."""
        agent_cfg = self.agents.get(agent_name)
        if agent_cfg and agent_cfg.llm:
            # Merge: agent overrides take precedence, defaults fill gaps
            base = self.llm.model_dump()
            override = agent_cfg.llm.model_dump(exclude_none=True)
            base.update(override)
            return LLMConfig(**base)
        return self.llm

    def is_agent_enabled(self, agent_name: str) -> bool:
        """Check if a specific agent is enabled."""
        agent_cfg = self.agents.get(agent_name)
        if agent_cfg is None:
            return True  # Enabled by default
        return agent_cfg.enabled
