"""Fallback-aware LLM provider wrapper.

Tries the primary provider, then falls back through alternatives
if the primary fails (network error, auth error, rate limit).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

from pydantic import BaseModel

from code_audit.config.models import LLMConfig
from code_audit.llm.provider import LLMProvider
from code_audit.llm.registry import create_provider

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """Wraps a primary provider with ordered fallbacks."""

    def __init__(self, config: LLMConfig):
        self._configs = [config] + list(config.fallbacks)
        self._providers: list[LLMProvider] = []
        self._active_index = 0

        # Eagerly create the primary provider; lazy-create fallbacks on failure
        try:
            self._providers.append(create_provider(config))
        except (ValueError, Exception) as e:
            logger.warning(f"Primary provider ({config.provider}/{config.model}) failed to init: {e}")
            self._providers.append(None)  # type: ignore[arg-type]

    def _get_or_create(self, index: int) -> LLMProvider | None:
        """Get or lazily create a provider at the given index."""
        while len(self._providers) <= index:
            self._providers.append(None)  # type: ignore[arg-type]

        if self._providers[index] is None and index < len(self._configs):
            try:
                self._providers[index] = create_provider(self._configs[index])
            except Exception as e:
                logger.warning(f"Fallback provider {index} failed to init: {e}")
                return None

        return self._providers[index]

    @property
    def model_name(self) -> str:
        p = self._get_or_create(self._active_index)
        return p.model_name if p else self._configs[0].model

    @property
    def provider_name(self) -> str:
        p = self._get_or_create(self._active_index)
        return p.provider_name if p else str(self._configs[0].provider)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        last_error: Exception | None = None

        for i in range(len(self._configs)):
            provider = self._get_or_create(i)
            if provider is None:
                continue

            try:
                result = await provider.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._active_index = i
                self._last_usage = provider.last_usage
                if i > 0:
                    logger.info(f"Using fallback provider: {provider.provider_name}/{provider.model_name}")
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider {provider.provider_name}/{provider.model_name} failed: {e}"
                )
                await asyncio.sleep(1.0)  # brief pause before trying next provider
                continue

        raise RuntimeError(
            f"All {len(self._configs)} providers failed. Last error: {last_error}"
        )

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> T:
        last_error: Exception | None = None

        for i in range(len(self._configs)):
            provider = self._get_or_create(i)
            if provider is None:
                continue

            try:
                result = await provider.complete_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._active_index = i
                self._last_usage = provider.last_usage
                if i > 0:
                    logger.info(f"Using fallback provider: {provider.provider_name}/{provider.model_name}")
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider {provider.provider_name}/{provider.model_name} failed: {e}"
                )
                await asyncio.sleep(1.0)  # brief pause before trying next provider
                continue

        raise RuntimeError(
            f"All {len(self._configs)} providers failed. Last error: {last_error}"
        )
