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

    elif config.provider in (LLMProviderEnum.OPENAI_COMPAT, LLMProviderEnum.NVIDIA):
        from code_audit.llm.openai_compat import OpenAICompatProvider

        # NVIDIA uses its own base URL and key env var
        base_url = config.base_url
        api_key_env = config.api_key_env
        if config.provider == LLMProviderEnum.NVIDIA:
            base_url = base_url or "https://integrate.api.nvidia.com/v1"
            api_key_env = api_key_env if api_key_env != "ANTHROPIC_API_KEY" else "NVIDIA_API_KEY"

        return OpenAICompatProvider(
            model=config.model,
            api_key_env=api_key_env,
            base_url=base_url,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")
