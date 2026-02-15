"""
LLM provider clients — backward-compatible re-export shim.

.. deprecated::
    The canonical implementation lives in ``src.llm.providers``.
    Import from ``src.llm.providers`` directly instead of ``src.agents.llm``.
"""
from src.llm.providers import (  # noqa: F401
    AnthropicLLM,
    BaseLLM,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
    OllamaLLM,
    OpenAILLM,
    VllmLLM,
    create_llm_client,
    create_llm_from_config,
    create_llm_provider,
)
from src.utils.exceptions import (  # noqa: F401
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
