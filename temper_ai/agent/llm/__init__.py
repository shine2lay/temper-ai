"""
LLM provider clients — backward-compatible re-export shim.

.. deprecated::
    The canonical implementation lives in ``temper_ai.llm.providers``.
    Import from ``temper_ai.llm.providers`` directly instead of ``temper_ai.agent.llm``.
"""
from temper_ai.llm.providers import (  # noqa: F401
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
from temper_ai.shared.utils.exceptions import (  # noqa: F401
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
