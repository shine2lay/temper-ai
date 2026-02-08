"""Factory functions for creating LLM provider instances."""
import warnings
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.agents.llm.anthropic_provider import AnthropicLLM
from src.agents.llm.base import BaseLLM, LLMProvider
from src.agents.llm.ollama import OllamaLLM
from src.agents.llm.openai_provider import OpenAILLM
from src.agents.llm.vllm_provider import VllmLLM
from src.utils.exceptions import LLMError

if TYPE_CHECKING:
    from src.schemas.agent_config import InferenceConfig

# Default port numbers for LLM providers
OLLAMA_DEFAULT_PORT = 11434

# Map of provider enums to their implementation classes
_PROVIDER_CLASSES = {
    LLMProvider.OLLAMA: OllamaLLM,
    LLMProvider.OPENAI: OpenAILLM,
    LLMProvider.ANTHROPIC: AnthropicLLM,
    LLMProvider.VLLM: VllmLLM,
}

# Default base URLs for providers that have well-known endpoints
_DEFAULT_BASE_URLS = {
    LLMProvider.OLLAMA: f"http://localhost:{OLLAMA_DEFAULT_PORT}",
    LLMProvider.OPENAI: "https://api.openai.com/v1",
    LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1",
}


def _resolve_provider_enum(provider_str: str) -> LLMProvider:
    """Resolve a provider string to an LLMProvider enum value.

    Args:
        provider_str: Provider name (case-insensitive).

    Returns:
        Matching LLMProvider enum value.

    Raises:
        LLMError: If provider_str does not match any known provider.
    """
    try:
        return LLMProvider(provider_str.lower())
    except ValueError:
        valid = [p.value for p in LLMProvider]
        raise LLMError(
            f"Unknown LLM provider '{provider_str}'. Valid providers: {valid}"
        )


def create_llm_provider(inference_config: "InferenceConfig") -> BaseLLM:
    """Create LLM provider from inference configuration.

    .. deprecated::
        Use :func:`create_llm_from_config` instead.  This function will be
        removed in a future release.

    Args:
        inference_config: Inference configuration object with attributes:
            provider, model, base_url, temperature, max_tokens, top_p,
            timeout_seconds, max_retries, retry_delay_seconds, api_key

    Returns:
        Initialized LLM provider instance

    Raises:
        LLMError: If provider type is unknown
    """
    warnings.warn(
        "create_llm_provider is deprecated, use create_llm_from_config instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_llm_from_config(inference_config)


def create_llm_from_config(inference_config: "InferenceConfig") -> BaseLLM:
    """Create LLM provider from an InferenceConfig object.

    This is the preferred factory for creating LLM providers from a full
    inference configuration (e.g. parsed from YAML workflow configs).

    Args:
        inference_config: Inference configuration with provider, model,
            base_url, temperature, max_tokens, top_p, timeout_seconds,
            max_retries, retry_delay_seconds, and api_key attributes.

    Returns:
        Initialized LLM provider instance.

    Raises:
        LLMError: If provider type is unknown or unsupported.
    """
    provider_enum = _resolve_provider_enum(inference_config.provider)

    if provider_enum not in _PROVIDER_CLASSES:
        valid = [p.value for p in LLMProvider]
        raise LLMError(
            f"Unsupported LLM provider '{provider_enum.value}'. "
            f"Valid providers: {valid}"
        )

    provider_class = _PROVIDER_CLASSES[provider_enum]
    base_url = inference_config.base_url or _DEFAULT_BASE_URLS.get(provider_enum, "")

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

    if provider_enum in (LLMProvider.OPENAI, LLMProvider.ANTHROPIC):
        # H-05: Resolve api_key_ref (prefer it over deprecated api_key)
        if inference_config.api_key_ref:
            # Secret resolution from environment variable matching the ref name
            import os
            api_key = os.getenv(inference_config.api_key_ref)
            if not api_key:
                raise ValueError(f"API key reference '{inference_config.api_key_ref}' not found in environment")
            common_params["api_key"] = api_key
        elif inference_config.api_key:
            # Fallback to deprecated direct api_key
            common_params["api_key"] = inference_config.api_key
        else:
            raise ValueError(f"No API key or api_key_ref provided for {provider_enum}")

    return provider_class(**common_params)  # type: ignore[abstract]


def create_llm_client(
    provider: str,
    model: str,
    base_url: str,
    api_key: Optional[str] = None,
    **kwargs: Any,
) -> BaseLLM:
    """Factory function to create LLM client based on provider.

    Use this when you have individual parameters (provider name, model, URL)
    rather than a full InferenceConfig object.

    Args:
        provider: Provider name (ollama, openai, anthropic, vllm).
        model: Model identifier.
        base_url: Base URL for API.
        api_key: API key (optional for local models).
        **kwargs: Additional parameters passed to LLM client.

    Returns:
        Configured LLM client instance.

    Raises:
        LLMError: If provider is unknown.
    """
    provider_enum = _resolve_provider_enum(provider)
    llm_class = _PROVIDER_CLASSES.get(provider_enum)

    if not llm_class:
        valid = [p.value for p in LLMProvider]
        raise LLMError(
            f"Unknown provider '{provider}'. Valid providers: {valid}"
        )

    return llm_class(  # type: ignore[abstract]
        model=model,
        base_url=base_url,
        api_key=api_key,
        **kwargs,
    )
