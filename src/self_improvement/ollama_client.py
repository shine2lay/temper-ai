"""
OllamaClient wrapper for M5 Self-Improvement system.

This module provides a simplified wrapper around the Ollama API for use
in M5's model selection and experimentation workflows. It wraps the existing
OllamaLLM provider with a simpler interface focused on text generation.

Usage:
    client = OllamaClient(model="llama3.1:8b")
    result = client.generate("Extract product info from: iPhone 15 Pro - $999")
    print(result)  # Generated text
"""

from typing import Optional

from src.agents.llm import LLMResponse, OllamaLLM  # M-04: Import from new location
from src.constants.durations import TIMEOUT_LONG
from src.self_improvement.constants import (
    DEFAULT_OLLAMA_PORT,
    DEFAULT_TEMPERATURE,
)

# Default sampling parameters for Ollama client
DEFAULT_TOP_P = 0.9  # Nucleus sampling threshold


class OllamaClient:
    """
    Simplified Ollama API wrapper for M5 experimentation.

    Wraps the existing OllamaLLM provider with a simpler interface
    focused on the generate() method used by M5 strategies and agents.

    This wrapper:
    - Provides a simple generate() method (returns str, not LLMResponse)
    - Uses sensible defaults for M5 experimentation
    - Delegates to OllamaLLM for actual API communication
    - Can be easily swapped in experiments (model selection strategy)

    Example:
        # Basic usage
        client = OllamaClient(model="llama3.1:8b")
        response = client.generate("What is the capital of France?")
        print(response)  # "Paris is the capital of France."

        # With custom parameters
        client = OllamaClient(
            model="qwen2.5:32b",
            temperature=0.3,
            max_tokens=512
        )
        response = client.generate("Extract: iPhone 15 - $999")
        print(response)  # Extracted product data

        # Used in M5 experiments (model selection)
        experiment_config = {
            "control": OllamaClient("llama3.1:8b"),
            "variant_a": OllamaClient("phi3:mini"),
            "variant_b": OllamaClient("mistral:7b"),
            "variant_c": OllamaClient("qwen2.5:32b"),
        }
    """

    def __init__(
        self,
        model: str,
        base_url: str = f"http://localhost:{DEFAULT_OLLAMA_PORT}",
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = 2048,
        top_p: float = DEFAULT_TOP_P,
        timeout: int = TIMEOUT_LONG,
    ):
        """
        Initialize OllamaClient.

        Args:
            model: Ollama model name (e.g., "llama3.1:8b", "mistral:7b")
            base_url: Ollama server URL (default: http://localhost:11434)
            temperature: Sampling temperature 0.0-1.0 (default: DEFAULT_TEMPERATURE)
            max_tokens: Maximum tokens to generate (default: 2048)
            top_p: Nucleus sampling parameter (default: DEFAULT_TOP_P)
            timeout: Request timeout in seconds (default: TIMEOUT_LONG)
        """
        self.model = model

        # Delegate to OllamaLLM for actual implementation
        self._llm = OllamaLLM(
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout=timeout,
        )

    def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate text completion from prompt.

        Simplified interface that returns just the generated text string,
        hiding the complexity of LLMResponse objects.

        Args:
            prompt: Input text prompt
            temperature: Override temperature for this request (optional)
            max_tokens: Override max_tokens for this request (optional)

        Returns:
            Generated text as string

        Raises:
            LLMError: If generation fails
            LLMTimeoutError: If request times out
            LLMRateLimitError: If rate limited (unlikely with local Ollama)

        Example:
            >>> client = OllamaClient("llama3.1:8b")
            >>> result = client.generate("Say hello")
            >>> print(result)
            "Hello! How can I assist you today?"

            >>> # With temperature override
            >>> result = client.generate("Write a poem", temperature=0.9)
            >>> print(result)
            "Roses are red, violets are blue..."
        """
        # Build kwargs for overrides
        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        # Call underlying LLM provider
        response: LLMResponse = self._llm.complete(prompt, context=None, **kwargs)

        # Return just the text content
        return response.content

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"OllamaClient(model='{self.model}')"
