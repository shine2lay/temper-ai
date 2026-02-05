"""Factory for creating LLM provider instances from configuration.

Encapsulates the provider selection and initialization logic that was
previously inline in StandardAgent.__init__.
"""
from typing import Dict, Any

from src.agents.llm_providers import (
    BaseLLM,
    OllamaLLM,
    OpenAILLM,
    AnthropicLLM,
    LLMProvider,
)

# Default port numbers for LLM providers
OLLAMA_DEFAULT_PORT = 11434


def create_llm_provider(inference_config: Any) -> BaseLLM:
    """Create LLM provider from inference configuration.

    Args:
        inference_config: Inference configuration object with attributes:
            provider, model, base_url, temperature, max_tokens, top_p,
            timeout_seconds, max_retries, retry_delay_seconds, api_key

    Returns:
        Initialized LLM provider instance

    Raises:
        ValueError: If provider type is unknown
    """
    provider_str = inference_config.provider.lower()

    try:
        provider = LLMProvider(provider_str)
    except ValueError:
        raise ValueError(f"Unknown LLM provider: {provider_str}")

    default_base_urls = {
        LLMProvider.OLLAMA: f"http://localhost:{OLLAMA_DEFAULT_PORT}",
        LLMProvider.OPENAI: "https://api.openai.com/v1",
        LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1",
    }

    provider_classes = {
        LLMProvider.OLLAMA: OllamaLLM,
        LLMProvider.OPENAI: OpenAILLM,
        LLMProvider.ANTHROPIC: AnthropicLLM,
    }

    if provider not in provider_classes:
        raise ValueError(f"Unknown LLM provider: {provider}")

    provider_class = provider_classes[provider]
    base_url = inference_config.base_url or default_base_urls[provider]

    common_params: Dict[str, Any] = {
        "model": inference_config.model,
        "base_url": base_url,
        "temperature": inference_config.temperature,
        "max_tokens": inference_config.max_tokens,
        "top_p": inference_config.top_p,
        "timeout": inference_config.timeout_seconds,
        "max_retries": inference_config.max_retries,
        "retry_delay": float(inference_config.retry_delay_seconds),
    }

    if provider in (LLMProvider.OPENAI, LLMProvider.ANTHROPIC):
        common_params["api_key"] = inference_config.api_key

    return provider_class(**common_params)  # type: ignore[abstract]
