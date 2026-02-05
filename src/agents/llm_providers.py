"""
LLM provider clients for multi-provider inference support.

This module is a backward-compatible re-export shim. The canonical implementation
has been split into src/agents/llm/ package:
- base.py: BaseLLM, LLMProvider, LLMResponse, LLMStreamChunk
- ollama.py: OllamaLLM
- openai_provider.py: OpenAILLM
- anthropic_provider.py: AnthropicLLM
- vllm_provider.py: vLLMLLM
- factory.py: create_llm_client
"""
# Preserve module-level names that tests mock (e.g., src.agents.llm_providers.httpx)
import httpx  # noqa: F401

# Re-export everything from the new package
from src.agents.llm.base import (
    BaseLLM,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
)
from src.agents.llm.ollama import OllamaLLM
from src.agents.llm.openai_provider import OpenAILLM
from src.agents.llm.anthropic_provider import AnthropicLLM
from src.agents.llm.vllm_provider import vLLMLLM
from src.agents.llm.factory import create_llm_client

# Re-export exceptions (many imports reference these from here)
from src.utils.exceptions import (
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMAuthenticationError,
)

__all__ = [
    # Base classes
    "BaseLLM",
    "LLMProvider",
    # Response types
    "LLMResponse",
    "LLMStreamChunk",
    # Exceptions (re-exported from utils.exceptions)
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
    # Provider implementations
    "OllamaLLM",
    "OpenAILLM",
    "AnthropicLLM",
    "vLLMLLM",
    # Factory
    "create_llm_client",
]
