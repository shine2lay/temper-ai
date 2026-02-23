"""
LLM provider clients for multi-provider inference support.

Supports Ollama, OpenAI, Anthropic, and vLLM with unified interface.
"""

from temper_ai.llm.providers.anthropic_provider import AnthropicLLM
from temper_ai.llm.providers.base import (
    BaseLLM,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
)
from temper_ai.llm.providers.factory import (
    create_llm_client,
    create_llm_from_config,
    create_llm_provider,
)
from temper_ai.llm.providers.ollama import OllamaLLM
from temper_ai.llm.providers.openai_provider import OpenAILLM
from temper_ai.llm.providers.vllm_provider import VllmLLM

# Re-export exceptions for convenience
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)

__all__ = [
    "BaseLLM",
    "LLMProvider",
    "LLMResponse",
    "LLMStreamChunk",
    "OllamaLLM",
    "OpenAILLM",
    "AnthropicLLM",
    "VllmLLM",
    "create_llm_client",
    "create_llm_from_config",
    "create_llm_provider",
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
]
