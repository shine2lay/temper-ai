"""Provider factory — create a provider instance from config parameters."""

import logging
import os
from typing import Any

from temper_ai.llm.providers.base import BaseLLM
from temper_ai.llm.providers.ollama import OllamaLLM
from temper_ai.llm.providers.openai import OpenAILLM
from temper_ai.llm.providers.vllm import VllmLLM

logger = logging.getLogger(__name__)

_PROVIDER_MAP: dict[str, type[BaseLLM]] = {
    "openai": OpenAILLM,
    "vllm": VllmLLM,
    "ollama": OllamaLLM,
}

_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com",
    "vllm": "http://localhost:8000",
    "ollama": "http://localhost:11434",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
}


def _register_optional_providers():
    """Register providers with optional SDK dependencies (lazy import)."""
    try:
        from temper_ai.llm.providers.anthropic import AnthropicLLM
        _PROVIDER_MAP["anthropic"] = AnthropicLLM
    except ImportError:
        pass
    try:
        from temper_ai.llm.providers.gemini import GeminiLLM
        _PROVIDER_MAP["gemini"] = GeminiLLM
    except ImportError:
        pass

    # Local-only providers (not shipped with the public repo).
    # Place a register_providers.py in local/ to register custom providers.
    try:
        from local.register_providers import register as _register_local
        _register_local(_PROVIDER_MAP)
    except ImportError:
        pass


_register_optional_providers()


def register_provider(name: str, cls: type[BaseLLM], default_base_url: str | None = None) -> None:
    """Register a custom LLM provider.

    Args:
        name: Provider name (e.g., "my_provider").
        cls: Provider class (must subclass BaseLLM).
        default_base_url: Default API URL for this provider.
    """
    _PROVIDER_MAP[name] = cls
    if default_base_url:
        _DEFAULT_BASE_URLS[name] = default_base_url


def create_provider(
    provider: str,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    **kwargs: Any,
) -> BaseLLM:
    """Create an LLM provider instance.

    Args:
        provider: Provider name ("openai", "vllm").
        model: Model identifier (e.g., "gpt-4o", "qwen3-next").
        base_url: API base URL. Uses provider default if not specified.
        api_key: API key directly. Takes precedence over api_key_env.
        api_key_env: Environment variable name holding the API key.
        **kwargs: Passed to provider (temperature, max_tokens, timeout, etc.).
    """
    provider_cls = _PROVIDER_MAP.get(provider)
    if provider_cls is None:
        raise ValueError(
            f"Unknown provider '{provider}'. Available: {sorted(_PROVIDER_MAP)}"
        )

    # Resolve API key: explicit > env var
    resolved_key = api_key
    if not resolved_key and api_key_env:
        resolved_key = os.environ.get(api_key_env)
        if not resolved_key:
            logger.warning("API key env var '%s' is not set", api_key_env)

    resolved_url = base_url or _DEFAULT_BASE_URLS.get(provider, "http://localhost:8000")

    init_kwargs: dict[str, Any] = {"model": model, "base_url": resolved_url, **kwargs}
    if resolved_key is not None:
        init_kwargs["api_key"] = resolved_key
    return provider_cls(**init_kwargs)
