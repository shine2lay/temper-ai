"""
LLM provider clients for multi-provider inference support.

.. deprecated::
    This module is a backward-compatible re-export shim. The canonical
    implementation has been split into the ``src.agents.llm`` package.
    Import directly from ``src.agents.llm`` instead.

Shim mapping:
- base.py: BaseLLM, LLMProvider, LLMResponse, LLMStreamChunk
- ollama.py: OllamaLLM
- openai_provider.py: OpenAILLM
- anthropic_provider.py: AnthropicLLM
- vllm_provider.py: VllmLLM
- factory.py: create_llm_client
"""
import importlib
import warnings
from typing import Any

# Preserve module-level names that tests mock (e.g., src.agents.llm_providers.httpx)
import httpx  # noqa: F401

# Map of names exported by this shim to their canonical module paths.
_SHIM_EXPORTS = {
    # Base classes
    "BaseLLM": "src.agents.llm.base",
    "LLMProvider": "src.agents.llm.base",
    "LLMResponse": "src.agents.llm.base",
    "LLMStreamChunk": "src.agents.llm.base",
    # Provider implementations
    "OllamaLLM": "src.agents.llm.ollama",
    "OpenAILLM": "src.agents.llm.openai_provider",
    "AnthropicLLM": "src.agents.llm.anthropic_provider",
    "VllmLLM": "src.agents.llm.vllm_provider",
    # Factory
    "create_llm_client": "src.agents.llm.factory",
    # Exceptions (re-exported from utils.exceptions)
    "LLMError": "src.utils.exceptions",
    "LLMTimeoutError": "src.utils.exceptions",
    "LLMRateLimitError": "src.utils.exceptions",
    "LLMAuthenticationError": "src.utils.exceptions",
}

__all__ = list(_SHIM_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _SHIM_EXPORTS:
        warnings.warn(
            f"Importing {name} from src.agents.llm_providers is deprecated. "
            f"Import from {_SHIM_EXPORTS[name]} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        mod = importlib.import_module(_SHIM_EXPORTS[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
