"""
LLM provider clients for multi-provider inference support.

Supports Ollama, OpenAI, Anthropic, and vLLM with unified interface.
"""
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

# Re-export exceptions for convenience
from src.utils.exceptions import (
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMAuthenticationError,
)

__all__ = [
    "BaseLLM",
    "LLMProvider",
    "LLMResponse",
    "LLMStreamChunk",
    "OllamaLLM",
    "OpenAILLM",
    "AnthropicLLM",
    "vLLMLLM",
    "create_llm_client",
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
]
