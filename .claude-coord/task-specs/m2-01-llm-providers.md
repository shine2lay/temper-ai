# Task: m2-01-llm-providers - Implement LLM provider clients (Ollama, OpenAI, Anthropic)

**Priority:** CRITICAL
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement LLM provider clients for Ollama (local), OpenAI, and Anthropic. Each provider should have a unified interface, handle retries, track tokens/cost, and support streaming. Focus on Ollama first since it's used in examples.

---

## Files to Create

- `src/agents/llm_providers/__init__.py` - Provider exports
- `src/agents/llm_providers/base.py` - BaseLLMProvider abstract class
- `src/agents/llm_providers/ollama.py` - Ollama client
- `src/agents/llm_providers/openai_provider.py` - OpenAI client
- `src/agents/llm_providers/anthropic_provider.py` - Anthropic client
- `src/agents/llm_providers/utils.py` - Token counting, cost estimation
- `tests/test_agents/test_llm_providers.py` - Provider tests with mocks

---

## Acceptance Criteria

### Base Provider Interface
- [ ] BaseLLMProvider abstract class
- [ ] Methods: generate(), generate_stream(), count_tokens(), estimate_cost()
- [ ] Unified response format (text, tokens, cost, latency)
- [ ] Error handling with retries
- [ ] Timeout support
- [ ] Request/response logging

### Ollama Provider (Priority 1)
- [ ] Connect to Ollama API (default: http://localhost:11434)
- [ ] Support all Ollama models (llama3.2, codellama, etc.)
- [ ] Handle streaming responses
- [ ] Parse token counts from response
- [ ] Retry on connection errors
- [ ] Tests with mock HTTP responses

### OpenAI Provider (Priority 2)
- [ ] Use official OpenAI SDK
- [ ] Support GPT-4, GPT-3.5 models
- [ ] Handle streaming responses
- [ ] Track tokens and cost accurately
- [ ] API key from environment
- [ ] Tests with mocked SDK

### Anthropic Provider (Priority 3)
- [ ] Use official Anthropic SDK
- [ ] Support Claude models
- [ ] Handle streaming responses
- [ ] Track tokens and cost
- [ ] API key from environment
- [ ] Tests with mocked SDK

### Utilities
- [ ] Token counting (tiktoken for OpenAI, approximations for others)
- [ ] Cost estimation per model (pricing table)
- [ ] Latency tracking
- [ ] Error classification (timeout, auth, rate limit, etc.)

### Testing
- [ ] Unit tests for each provider with mocks
- [ ] Test retry logic
- [ ] Test timeout handling
- [ ] Test streaming
- [ ] Test token/cost calculation
- [ ] Coverage > 85%

---

## Implementation Details

**src/agents/llm_providers/base.py:**
```python
"""Base LLM provider interface."""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Iterator
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Unified LLM response format."""
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: int
    model: str
    provider: str


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with config."""
        self.config = config
        self.model = config["model"]
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 2048)
        self.timeout = config.get("timeout_seconds", 60)
        self.max_retries = config.get("max_retries", 3)

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate completion from prompt."""
        pass

    @abstractmethod
    def generate_stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Generate completion with streaming."""
        pass

    def count_tokens(self, text: str) -> int:
        """Estimate token count."""
        # Default: ~4 chars per token
        return len(text) // 4

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost in USD."""
        return 0.0  # Override in subclasses
```

**src/agents/llm_providers/ollama.py:**
```python
"""Ollama provider implementation."""
import httpx
import time
from typing import Dict, Any, Iterator
from .base import BaseLLMProvider, LLMResponse


class OllamaProvider(BaseLLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.client = httpx.Client(timeout=self.timeout)

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate completion."""
        start_time = time.time()

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            }
        }

        for attempt in range(self.max_retries):
            try:
                response = self.client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                latency_ms = int((time.time() - start_time) * 1000)

                return LLMResponse(
                    text=data["response"],
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0),
                    total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                    estimated_cost_usd=0.0,  # Local = free
                    latency_ms=latency_ms,
                    model=self.model,
                    provider="ollama"
                )
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff

    def generate_stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Generate with streaming."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
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

---

## Test Strategy

```python
def test_ollama_generate():
    """Test Ollama completion."""
    # Mock httpx response
    provider = OllamaProvider({"model": "llama3.2:3b"})
    response = provider.generate("Hello")
    assert isinstance(response, LLMResponse)
    assert response.provider == "ollama"

def test_retry_on_failure():
    """Test retry logic."""
    # Mock failure then success
    pass

def test_streaming():
    """Test streaming response."""
    # Mock streaming chunks
    pass
```

---

## Success Metrics

- [ ] All 3 providers implemented
- [ ] Ollama provider works with real local Ollama
- [ ] Unified interface for all providers
- [ ] Retry and timeout handling works
- [ ] Tests pass > 85% coverage

---

## Dependencies

- **Blocked by:** m1-00-structure
- **Blocks:** m2-04-agent-runtime
- **Integrates with:** None (standalone)

---

## Design References

- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
- OpenAI SDK: https://platform.openai.com/docs/api-reference
- Anthropic SDK: https://docs.anthropic.com/

---

## Notes

- Focus on Ollama first (used in demos)
- OpenAI and Anthropic can be simpler wrappers around official SDKs
- Local models (Ollama) have zero cost but still track tokens
- Consider adding vLLM support later
