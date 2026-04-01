"""Abstract LLM provider interface."""

from __future__ import annotations

import abc
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(abc.ABC):
    """Abstract base class for LLM providers.

    Each provider implements two methods:
    - complete(): Raw text completion
    - complete_structured(): Structured output that returns a Pydantic model
    """

    @abc.abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        """Send a prompt and get a text response."""
        ...

    @abc.abstractmethod
    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> T:
        """Send a prompt and get a structured response as a Pydantic model.

        The provider is responsible for ensuring the response validates
        against the Pydantic model -- either via native structured output
        (Claude's messages.parse, Gemini's response_json_schema) or
        via parsing + retry.
        """
        ...

    @property
    def last_usage(self) -> dict[str, int]:
        """Token usage from the most recent API call."""
        return getattr(self, '_last_usage', {"input_tokens": 0, "output_tokens": 0})

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
        ...

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (claude, gemini, openai_compat)."""
        ...
