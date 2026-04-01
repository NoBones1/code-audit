"""OpenAI-compatible API provider.

Works with any endpoint that implements the OpenAI chat completions API:
- OpenAI
- Ollama
- LM Studio
- vLLM
- Together AI
- etc.
"""

from __future__ import annotations

import json
import os
from typing import TypeVar

import httpx
from pydantic import BaseModel

from code_audit.llm.provider import LLMProvider

T = TypeVar("T", bound=BaseModel)


class OpenAICompatProvider(LLMProvider):
    """Provider for any OpenAI-compatible API endpoint."""

    DEFAULT_TIMEOUT_SECONDS = 300.0  # 5 min — large context LLM calls can be slow

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str | None = None,
    ):
        self._model = model
        self._api_key = os.environ.get(api_key_env, "")
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai_compat"

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> str:
        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT_SECONDS) as client:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage", {})
            self._last_usage = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }
            return data["choices"][0]["message"]["content"]

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.2,
        max_tokens: int = 8192,
    ) -> T:
        schema = response_model.model_json_schema()

        # Instruct the model to output JSON matching the schema
        json_system = (
            f"{system_prompt}\n\n"
            f"IMPORTANT: Respond with ONLY a valid JSON object matching this schema:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```\n"
            f"Do not include any text before or after the JSON."
        )

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT_SECONDS) as client:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            body: dict = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": json_system},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            # Try response_format if supported (OpenAI-native)
            body["response_format"] = {"type": "json_object"}

            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage", {})
            self._last_usage = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }
            text = data["choices"][0]["message"]["content"]

            # Strip markdown code blocks if present
            text = text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])

            return response_model.model_validate_json(text)
