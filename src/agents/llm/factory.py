"""Factory function for creating LLM clients."""
from typing import Any, Optional

from src.agents.llm.base import BaseLLM, LLMProvider
from src.agents.llm.ollama import OllamaLLM
from src.agents.llm.openai_provider import OpenAILLM
from src.agents.llm.anthropic_provider import AnthropicLLM
from src.agents.llm.vllm_provider import vLLMLLM


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
        LLMProvider.VLLM: vLLMLLM,
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
