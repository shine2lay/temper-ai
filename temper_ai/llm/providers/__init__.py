"""LLM providers."""

from temper_ai.llm.providers.base import BaseLLM, StreamCallback
from temper_ai.llm.providers.factory import create_provider, register_provider
from temper_ai.llm.providers.openai import OpenAILLM
from temper_ai.llm.providers.vllm import VllmLLM
from temper_ai.llm.providers.ollama import OllamaLLM

# Optional providers (require extra SDKs)
try:
    from temper_ai.llm.providers.anthropic import AnthropicLLM
except ImportError:
    AnthropicLLM = None  # type: ignore

try:
    from temper_ai.llm.providers.gemini import GeminiLLM
except ImportError:
    GeminiLLM = None  # type: ignore

__all__ = [
    "AnthropicLLM",
    "BaseLLM",
    "GeminiLLM",
    "OllamaLLM",
    "OpenAILLM",
    "StreamCallback",
    "VllmLLM",
    "create_provider",
    "register_provider",
]
