"""LLM provider abstraction layer."""

from code_audit.llm.provider import LLMProvider
from code_audit.llm.registry import create_provider

__all__ = ["LLMProvider", "create_provider"]
