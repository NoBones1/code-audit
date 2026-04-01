"""Google Gemini LLM provider.

Uses google-genai SDK with response_json_schema for structured output.
"""

from __future__ import annotations

import json
import os
from typing import TypeVar

from pydantic import BaseModel

from code_audit.llm.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)


class GeminiProvider(LLMProvider):
    """Gemini provider using the google-genai SDK."""

    def __init__(self, model: str = "gemini-2.5-flash", api_key_env: str = "GEMINI_API_KEY"):
        self._model = model
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise ValueError(
                f"Environment variable {api_key_env} is not set. "
                f"Set it with: export {api_key_env}=your-api-key"
            )
        from google import genai

        self._client = genai.Client(api_key=api_key)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        self._last_usage = {
            "input_tokens": getattr(getattr(response, 'usage_metadata', None), 'prompt_token_count', 0) or 0,
            "output_tokens": getattr(getattr(response, 'usage_metadata', None), 'candidates_token_count', 0) or 0,
        }
        return response.text or ""

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> T:
        from google.genai import types

        schema = response_model.model_json_schema()

        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        self._last_usage = {
            "input_tokens": getattr(getattr(response, 'usage_metadata', None), 'prompt_token_count', 0) or 0,
            "output_tokens": getattr(getattr(response, 'usage_metadata', None), 'candidates_token_count', 0) or 0,
        }
        text = response.text or "{}"
        return response_model.model_validate_json(text)
