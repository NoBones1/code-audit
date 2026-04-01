"""Usage tracking and cost calculation for LLM API calls."""

from __future__ import annotations
from pydantic import BaseModel, Field

# Pricing: (input_per_1m_tokens, output_per_1m_tokens, note)
MODEL_PRICING: dict[str, tuple[float, float, str]] = {
    # NVIDIA Build free tier
    "moonshotai/kimi-k2.5": (0.0, 0.0, "NVIDIA Build free tier"),
    "nvidia/nemotron-3-super-120b-a12b": (0.0, 0.0, "NVIDIA Build free tier"),
    "minimaxi/minimax-m2.5": (0.0, 0.0, "NVIDIA Build free tier"),
    "zhipu/glm-5": (0.0, 0.0, "NVIDIA Build free tier"),
    "meta/llama-4-maverick-17b-128e-instruct": (0.0, 0.0, "NVIDIA Build free tier"),
    # Gemini free tier
    "gemini-2.5-flash": (0.0, 0.0, "Gemini free tier"),
    "gemini-2.5-flash-lite": (0.0, 0.0, "Gemini free tier"),
    # OpenRouter free tier
    "meta-llama/llama-3.3-70b-instruct:free": (0.0, 0.0, "OpenRouter free tier"),
    # Claude (paid — direct Anthropic)
    "claude-sonnet-4-6": (3.0, 15.0, "per 1M tokens"),
    "claude-opus-4-6": (15.0, 75.0, "per 1M tokens"),
    "claude-haiku-4-5": (0.80, 4.0, "per 1M tokens"),
    # Claude via Venice.ai (DIEM credits)
    "claude-sonnet-4.6": (3.6, 18.0, "Venice.ai DIEM credits"),
    # Gemini paid
    "gemini-2.5-pro": (1.25, 10.0, "per 1M tokens"),
}

def get_pricing(model: str) -> tuple[float, float, str]:
    """Look up pricing for a model. Returns (input_per_1m, output_per_1m, note)."""
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Check partial match (model name without provider prefix)
    for key, val in MODEL_PRICING.items():
        if key in model or model in key:
            return val
    return (0.0, 0.0, "unknown model (assuming free)")

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given token usage."""
    input_rate, output_rate, _ = get_pricing(model)
    return (input_tokens * input_rate / 1_000_000) + (output_tokens * output_rate / 1_000_000)


class UsageRecord(BaseModel):
    """Token usage and cost for a single agent run."""
    agent_name: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def is_free(self) -> bool:
        return self.cost_usd == 0.0

    @property
    def pricing_note(self) -> str:
        _, _, note = get_pricing(self.model)
        return note

    def format_display(self) -> str:
        """Format for terminal display."""
        cost_str = f"${self.cost_usd:.2f}" if self.cost_usd > 0 else "$0.00"
        return (
            f"{self.agent_name}: "
            f"{self.input_tokens:,} input + {self.output_tokens:,} output tokens "
            f"-> {cost_str} ({self.pricing_note})"
        )


class AuditUsageSummary(BaseModel):
    """Aggregated usage across all agents in a review."""
    records: list[UsageRecord] = Field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def all_free(self) -> bool:
        return all(r.is_free for r in self.records)

    def equivalent_cost(self, model: str = "claude-sonnet-4-6") -> float:
        """What this review would have cost on a different model."""
        input_rate, output_rate, _ = get_pricing(model)
        return (
            self.total_input_tokens * input_rate / 1_000_000
            + self.total_output_tokens * output_rate / 1_000_000
        )
