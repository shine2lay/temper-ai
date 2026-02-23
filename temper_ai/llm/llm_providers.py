"""
LLM provider clients for multi-provider inference support.

.. deprecated::
    This module is a backward-compatible re-export shim. The canonical
    implementation has been split into the ``temper_ai.llm.providers`` package.
    Import directly from ``temper_ai.llm.providers`` instead.

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

# Preserve module-level names that tests mock (e.g., temper_ai.llm.llm_providers.httpx)
import httpx  # noqa: F401

# Map of names exported by this shim to their canonical module paths.
_SHIM_EXPORTS = {
    # Base classes
    "BaseLLM": "temper_ai.llm.providers.base",
    "LLMProvider": "temper_ai.llm.providers.base",
    "LLMResponse": "temper_ai.llm.providers.base",
    "LLMStreamChunk": "temper_ai.llm.providers.base",
    # Provider implementations
    "OllamaLLM": "temper_ai.llm.providers.ollama",
    "OpenAILLM": "temper_ai.llm.providers.openai_provider",
    "AnthropicLLM": "temper_ai.llm.providers.anthropic_provider",
    "VllmLLM": "temper_ai.llm.providers.vllm_provider",
    # Factory
    "create_llm_client": "temper_ai.llm.providers.factory",
    # Exceptions (re-exported from utils.exceptions)
    "LLMError": "temper_ai.shared.utils.exceptions",
    "LLMTimeoutError": "temper_ai.shared.utils.exceptions",
    "LLMRateLimitError": "temper_ai.shared.utils.exceptions",
    "LLMAuthenticationError": "temper_ai.shared.utils.exceptions",
}

__all__ = list(_SHIM_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _SHIM_EXPORTS:
        warnings.warn(
            f"Importing {name} from temper_ai.llm.llm_providers is deprecated. "
            f"Import from {_SHIM_EXPORTS[name]} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        mod = importlib.import_module(_SHIM_EXPORTS[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
