"""LLM provider factory -- creates provider instances from config."""

from __future__ import annotations

from code_audit.config.models import LLMConfig, LLMProvider as LLMProviderEnum
from code_audit.llm.provider import LLMProvider


def create_provider(config: LLMConfig) -> LLMProvider:
    """Create an LLM provider instance from configuration.

    Args:
        config: LLM configuration specifying provider, model, and credentials.

    Returns:
        An initialized LLMProvider instance.

    Raises:
        ValueError: If the provider type is not supported.
    """
    if config.provider == LLMProviderEnum.CLAUDE:
        from code_audit.llm.claude import ClaudeProvider

        return ClaudeProvider(
            model=config.model,
            api_key_env=config.api_key_env,
        )

    elif config.provider == LLMProviderEnum.GEMINI:
        from code_audit.llm.gemini import GeminiProvider

        return GeminiProvider(
            model=config.model,
            api_key_env=config.api_key_env,
        )

    elif config.provider == LLMProviderEnum.OPENAI_COMPAT:
        from code_audit.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            model=config.model,
            api_key_env=config.api_key_env,
            base_url=config.base_url,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")
