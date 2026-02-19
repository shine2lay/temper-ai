# LLM Provider Interface

## Overview

The LLM provider interface abstracts different LLM backends (Ollama, OpenAI, Anthropic, vLLM) behind a unified interface. All providers support text generation, streaming, token counting, and cost estimation.

## Class Hierarchy

```
BaseLLMProvider (ABC)
    │
    ├─ OllamaProvider
    │   └─ Local models (llama3.2, codellama, etc.)
    │
    ├─ OpenAIProvider
    │   └─ GPT-4, GPT-3.5-turbo
    │
    ├─ AnthropicProvider
    │   └─ Claude-3.5-sonnet, etc.
    │
    └─ vLLMProvider (future)
        └─ Custom deployed models
```

## Interface Definition

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Iterator


@dataclass
class LLMResponse:
    """Unified LLM response format."""
    text: str                    # Generated text
    prompt_tokens: int           # Tokens in prompt
    completion_tokens: int       # Tokens in completion
    total_tokens: int            # Total tokens
    estimated_cost_usd: float    # Estimated cost
    latency_ms: int              # Time taken (ms)
    model: str                   # Model used
    provider: str                # Provider name


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider.

        Args:
            config: Provider configuration dict
                - model: str
                - temperature: float
                - max_tokens: int
                - timeout_seconds: int
                - max_retries: int
                - (provider-specific fields)
        """
        self.model = config["model"]
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 2048)
        self.timeout = config.get("timeout_seconds", 60)
        self.max_retries = config.get("max_retries", 3)

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate completion from prompt.

        Args:
            prompt: Input prompt
            **kwargs: Additional parameters (override defaults)

        Returns:
            LLMResponse with text, tokens, cost, latency

        Raises:
            LLMError: On generation failure
        """
        pass

    @abstractmethod
    def generate_stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Generate completion with streaming.

        Args:
            prompt: Input prompt
            **kwargs: Additional parameters

        Yields:
            Text chunks as they arrive
        """
        pass

    def count_tokens(self, text: str) -> int:
        """Estimate token count.

        Default: ~4 chars per token
        Override for better accuracy.
        """
        return len(text) // 4

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int
    ) -> float:
        """Estimate cost in USD.

        Override in subclasses with actual pricing.
        """
        return 0.0
```

## Provider Implementations

### OllamaProvider

```python
class OllamaProvider(BaseLLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.client = httpx.Client(timeout=self.timeout)

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate with Ollama API."""
        start_time = time.time()

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "num_predict": kwargs.get("max_tokens", self.max_tokens),
            }
        }

        # Retry loop
        for attempt in range(self.max_retries):
            try:
                response = self.client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                return LLMResponse(
                    text=data["response"],
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0),
                    total_tokens=data.get("prompt_eval_count", 0) +
                                data.get("eval_count", 0),
                    estimated_cost_usd=0.0,  # Local = free
                    latency_ms=int((time.time() - start_time) * 1000),
                    model=self.model,
                    provider="ollama"
                )
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise LLMError(f"Ollama generation failed: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff

    def generate_stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Stream generation."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "num_predict": kwargs.get("max_tokens", self.max_tokens),
            }
        }

        with self.client.stream(
            "POST",
            f"{self.base_url}/api/generate",
            json=payload
        ) as response:
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if "response" in data:
                        yield data["response"]
```

### OpenAIProvider

```python
class OpenAIProvider(BaseLLMProvider):
    """OpenAI API provider."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from openai import OpenAI

        self.client = OpenAI(
            api_key=config.get("api_key", os.getenv("OPENAI_API_KEY"))
        )

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate with OpenAI API."""
        start_time = time.time()

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )

        usage = response.usage

        return LLMResponse(
            text=response.choices[0].message.content,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            estimated_cost_usd=self.estimate_cost(
                usage.prompt_tokens,
                usage.completion_tokens
            ),
            latency_ms=int((time.time() - start_time) * 1000),
            model=self.model,
            provider="openai"
        )

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate OpenAI cost."""
        # Prices as of 2026 (example)
        pricing = {
            "gpt-4-turbo": (0.01, 0.03),      # (input, output) per 1K tokens
            "gpt-3.5-turbo": (0.0005, 0.0015),
        }

        input_price, output_price = pricing.get(self.model, (0, 0))

        return (
            (prompt_tokens / 1000) * input_price +
            (completion_tokens / 1000) * output_price
        )
```

### AnthropicProvider

```python
class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from anthropic import Anthropic

        self.client = Anthropic(
            api_key=config.get("api_key", os.getenv("ANTHROPIC_API_KEY"))
        )

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate with Claude."""
        start_time = time.time()

        response = self.client.messages.create(
            model=self.model,
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            temperature=kwargs.get("temperature", self.temperature),
            messages=[{"role": "user", "content": prompt}]
        )

        return LLMResponse(
            text=response.content[0].text,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            estimated_cost_usd=self.estimate_cost(
                response.usage.input_tokens,
                response.usage.output_tokens
            ),
            latency_ms=int((time.time() - start_time) * 1000),
            model=self.model,
            provider="anthropic"
        )
```

## Configuration

```yaml
# In agent config
inference:
  provider: ollama           # or: openai, anthropic
  model: llama3.2:3b         # Model name
  base_url: http://localhost:11434  # For Ollama/vLLM
  api_key: ${OPENAI_API_KEY} # For OpenAI/Anthropic
  temperature: 0.7
  max_tokens: 2048
  top_p: 0.9
  timeout_seconds: 60
  max_retries: 3
```

## Usage Example

```python
from temper_ai.agents.llm_providers import OllamaProvider, OpenAIProvider

# Create Ollama provider
ollama_config = {
    "model": "llama3.2:3b",
    "base_url": "http://localhost:11434",
    "temperature": 0.7,
    "max_tokens": 2048,
}
ollama = OllamaProvider(ollama_config)

# Generate
response = ollama.generate("What is TypeScript?")
print(response.text)
print(f"Tokens: {response.total_tokens}")
print(f"Cost: ${response.estimated_cost_usd:.4f}")
print(f"Latency: {response.latency_ms}ms")

# Streaming
for chunk in ollama.generate_stream("Write a poem"):
    print(chunk, end="", flush=True)
```

## Provider Comparison

| Feature | Ollama | OpenAI | Anthropic |
|---------|--------|--------|-----------|
| Local | ✅ Yes | ❌ No | ❌ No |
| Cost | Free | Paid | Paid |
| Streaming | ✅ Yes | ✅ Yes | ✅ Yes |
| Token counting | ✅ Accurate | ✅ Accurate | ✅ Accurate |
| API key | ❌ No | ✅ Yes | ✅ Yes |
| Latency | Low (local) | Medium | Medium |

## Error Handling

```python
from temper_ai.agents.llm_providers.exceptions import (
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMAuthenticationError
)

try:
    response = provider.generate(prompt)
except LLMTimeoutError:
    # Handle timeout
    pass
except LLMRateLimitError:
    # Handle rate limit
    pass
except LLMAuthenticationError:
    # Handle auth error
    pass
except LLMError as e:
    # Generic LLM error
    pass
```

## Response Flow

```
provider.generate(prompt)
    │
    ├─ 1. Prepare request
    │      ├─ Format payload
    │      ├─ Add parameters
    │      └─ Set timeout
    │
    ├─ 2. Call API (with retries)
    │      ├─ Attempt 1
    │      ├─ (Fail?) Exponential backoff
    │      ├─ Attempt 2
    │      └─ (Fail?) Raise LLMError
    │
    ├─ 3. Parse response
    │      ├─ Extract text
    │      ├─ Count tokens
    │      └─ Calculate cost
    │
    └─ 4. Return LLMResponse
           ├─ text: "..."
           ├─ tokens: 150
           ├─ cost: $0.002
           └─ latency: 250ms
```

## Key Design Points

1. **Unified interface** - All providers implement same methods
2. **Retry logic** - Automatic retries with exponential backoff
3. **Cost tracking** - Estimate cost per call
4. **Token counting** - Accurate token usage
5. **Streaming support** - All providers support streaming
6. **Error handling** - Specific exception types

## Related Documentation

- [Agent Interface](./agent_interface.md)
- [Configuration Schema](./config_schema.md)
