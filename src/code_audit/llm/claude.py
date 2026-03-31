"""Anthropic Claude LLM provider.

Uses the Anthropic SDK's messages.parse() for structured output,
which guarantees valid JSON matching the Pydantic schema.
"""

from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel

from code_audit.llm.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)


class ClaudeProvider(LLMProvider):
    """Claude provider using the Anthropic Python SDK."""

    def __init__(self, model: str = "claude-sonnet-4-6", api_key_env: str = "ANTHROPIC_API_KEY"):
        self._model = model
        self._api_key = os.environ.get(api_key_env, "")
        if not self._api_key:
            raise ValueError(
                f"Environment variable {api_key_env} is not set. "
                f"Set it with: export {api_key_env}=your-api-key"
            )
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "claude"

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Extract text from response content blocks
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "\n".join(text_parts)

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> T:
        """Use Claude's structured output via messages.create with output_config.

        Falls back to manual JSON parsing if the SDK version doesn't support
        messages.parse().
        """
        import json

        import anthropic

        # Build the JSON schema from the Pydantic model
        schema = response_model.model_json_schema()

        try:
            # Try using output_config (GA structured output)
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": schema,
                    }
                },
            )
            # Parse the JSON response
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            return response_model.model_validate_json(text)

        except (anthropic.BadRequestError, TypeError):
            # Fallback: instruct model to output JSON and parse manually
            json_prompt = (
                f"{system_prompt}\n\n"
                f"IMPORTANT: Respond with ONLY a valid JSON object matching this schema:\n"
                f"```json\n{json.dumps(schema, indent=2)}\n```\n"
                f"Do not include any text before or after the JSON."
            )
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=json_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            # Extract JSON from possible markdown code blocks
            text = text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])

            return response_model.model_validate_json(text)
