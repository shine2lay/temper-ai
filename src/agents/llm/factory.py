"""Factory functions for creating LLM provider instances."""
from typing import Any, Dict, Optional

from src.agents.llm.anthropic_provider import AnthropicLLM
from src.agents.llm.base import BaseLLM, LLMProvider
from src.agents.llm.ollama import OllamaLLM
from src.agents.llm.openai_provider import OpenAILLM
from src.agents.llm.vllm_provider import VllmLLM

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


def create_llm_client(
    provider: str,
    model: str,
    base_url: str,
    api_key: Optional[str] = None,
    **kwargs: Any
) -> BaseLLM:
    """
    Factory function to create LLM client based on provider.

    Args:
        provider: Provider name (ollama, openai, anthropic, vllm)
        model: Model identifier
        base_url: Base URL for API
        api_key: API key (optional for local models)
        **kwargs: Additional parameters passed to LLM client

    Returns:
        Configured LLM client instance

    Raises:
        ValueError: If provider is unknown
    """
    providers = {
        LLMProvider.OLLAMA: OllamaLLM,
        LLMProvider.OPENAI: OpenAILLM,
        LLMProvider.ANTHROPIC: AnthropicLLM,
        LLMProvider.VLLM: VllmLLM,
    }

    provider_enum = LLMProvider(provider.lower())
    llm_class = providers.get(provider_enum)

    if not llm_class:
        raise ValueError(
            f"Unknown provider: {provider}. "
            f"Supported: {', '.join(p.value for p in LLMProvider)}"
        )

    return llm_class(  # type: ignore[abstract]
        model=model,
        base_url=base_url,
        api_key=api_key,
        **kwargs
    )
