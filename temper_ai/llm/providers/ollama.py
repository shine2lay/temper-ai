"""Ollama LLM provider — uses OpenAI-compatible API.

Ollama exposes an OpenAI-compatible endpoint at /v1/chat/completions.
This provider extends OpenAILLM with Ollama-specific defaults.

No API key required. Default base URL: http://localhost:11434
"""

from temper_ai.llm.providers.openai import OpenAILLM


class OllamaLLM(OpenAILLM):
    """Provider for Ollama (local models via OpenAI-compatible API)."""

    PROVIDER_NAME = "ollama"

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        **kwargs,
    ):
        super().__init__(
            model=model,
            base_url=base_url,
            api_key="ollama",  # Ollama doesn't need a key but the field is required
            **kwargs,
        )
