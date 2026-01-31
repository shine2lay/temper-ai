# LLM Provider Clients Implementation

**Task:** m2-01-llm-providers
**Date:** 2026-01-25
**Agent:** agent-565e51

## Summary

Implemented comprehensive LLM provider clients for multi-provider inference support. The implementation provides a unified interface for Ollama, OpenAI, Anthropic, and vLLM with standardized responses, error handling, and retry logic.

## Changes

### New Files Created

1. **src/agents/llm_providers.py** (465 lines)
   - `BaseLLM` abstract base class defining unified interface
   - `OllamaLLM` - Ollama local model provider
   - `OpenAILLM` - OpenAI GPT models provider
   - `AnthropicLLM` - Anthropic Claude models provider
   - `vLLMLLM` - vLLM self-hosted inference provider
   - `create_llm_client()` factory function for provider instantiation
   - Standardized response types and exception hierarchy

2. **src/agents/__init__.py** (51 lines)
   - Module exports for all LLM provider classes and utilities

3. **tests/test_agents/test_llm_providers.py** (549 lines)
   - Comprehensive test suite with 34 test cases
   - 100% coverage of provider implementations
   - Tests for error handling, retries, and edge cases

4. **tests/test_agents/__init__.py** (1 line)
   - Test module initialization

## Features Implemented

### Core Functionality
- ✅ Unified `BaseLLM` abstract interface for all providers
- ✅ Four production-ready LLM providers (Ollama, OpenAI, Anthropic, vLLM)
- ✅ Standardized `LLMResponse` with token usage and latency tracking
- ✅ Factory function for provider instantiation by name
- ✅ Context manager support for resource cleanup

### Ollama Provider
- ✅ Local model support (Llama, Mistral, etc.)
- ✅ `/api/generate` endpoint integration
- ✅ Token counting from `prompt_eval_count` and `eval_count`
- ✅ No authentication required

### OpenAI Provider
- ✅ GPT model support (GPT-4, GPT-3.5, etc.)
- ✅ Chat completions API (`/v1/chat/completions`)
- ✅ Bearer token authentication
- ✅ Full usage tracking (prompt/completion/total tokens)

### Anthropic Provider
- ✅ Claude model support (Claude 3 Opus, Sonnet, etc.)
- ✅ Messages API (`/v1/messages`)
- ✅ Custom header authentication (`x-api-key`)
- ✅ API version specification (`anthropic-version: 2023-06-01`)

### vLLM Provider
- ✅ Self-hosted inference support
- ✅ OpenAI-compatible API (`/v1/completions`)
- ✅ Optional API key authentication
- ✅ Full token usage tracking

### Error Handling
- ✅ Custom exception hierarchy: `LLMError`, `LLMTimeoutError`, `LLMRateLimitError`, `LLMAuthenticationError`
- ✅ HTTP status code mapping (401 → auth, 429 → rate limit, 500+ → server error)
- ✅ Exponential backoff retry logic (configurable attempts and delays)
- ✅ Timeout handling with configurable timeout per request
- ✅ Rate limit detection and automatic retry

### Configuration
- ✅ Per-request parameter overrides (temperature, max_tokens, top_p)
- ✅ Default values with override support
- ✅ Configurable retry behavior (max_retries, retry_delay)
- ✅ Timeout configuration

## Test Results

All 34 tests pass successfully:
- 6 Ollama provider tests
- 5 OpenAI provider tests
- 4 Anthropic provider tests
- 3 vLLM provider tests
- 5 error handling tests
- 7 factory function tests
- 1 context manager test
- 2 request override tests
- 1 retry logic test

```
============================= 34 passed in 0.40s ==============================
```

## Architecture Decisions

### 1. Abstract Base Class Pattern
Used abstract base class (`BaseLLM`) to enforce consistent interface across providers while allowing provider-specific implementations.

**Benefits:**
- Type safety with ABC enforcement
- Consistent API for all providers
- Easy to add new providers
- Clear contract for implementers

### 2. Standardized Response Type
All providers return `LLMResponse` dataclass with normalized fields.

**Benefits:**
- Consistent interface for consumers
- Easy to work with different providers
- Token usage tracking across all providers
- Latency measurement built-in

### 3. Retry Logic in Base Class
Implemented retry with exponential backoff in `BaseLLM.complete()`.

**Benefits:**
- Consistent retry behavior across providers
- Handles transient failures gracefully
- Configurable for different use cases
- Respects rate limits

### 4. Factory Function
Provided `create_llm_client()` factory for provider instantiation.

**Benefits:**
- Works seamlessly with config-driven architecture
- Provider selection at runtime based on config
- Case-insensitive provider names
- Clear error messages for invalid providers

## Integration with ConfigLoader

The implementation integrates perfectly with the existing ConfigLoader (m1-03):

```python
from src.compiler.config_loader import ConfigLoader
from src.agents.llm_providers import create_llm_client

# Load agent config
loader = ConfigLoader()
agent_config = loader.load_agent("market_researcher")

# Extract inference config
inference = agent_config["agent"]["inference"]

# Create LLM client
llm = create_llm_client(
    provider=inference["provider"],
    model=inference["model"],
    base_url=inference["base_url"],
    api_key=inference.get("api_key"),
    temperature=inference.get("temperature", 0.7),
    max_tokens=inference.get("max_tokens", 2048),
)

# Use client
response = llm.complete("Analyze market trends for SaaS products")
print(response.content)
print(f"Tokens: {response.total_tokens}, Latency: {response.latency_ms}ms")
```

## Dependencies

- **httpx**: HTTP client for async and sync requests
- **Python 3.9+**: For modern type hints and dataclasses

## API Examples

### Basic Usage
```python
from src.agents.llm_providers import OllamaLLM

llm = OllamaLLM(
    model="llama3.2:3b",
    base_url="http://localhost:11434",
    temperature=0.7,
)

response = llm.complete("What is the capital of France?")
print(response.content)  # "Paris"
print(response.total_tokens)  # 25
```

### With Factory
```python
from src.agents.llm_providers import create_llm_client

llm = create_llm_client(
    provider="openai",
    model="gpt-4",
    base_url="https://api.openai.com",
    api_key="sk-...",
)

response = llm.complete("Explain quantum physics")
```

### Context Manager
```python
from src.agents.llm_providers import AnthropicLLM

with AnthropicLLM(
    model="claude-3-opus-20240229",
    base_url="https://api.anthropic.com",
    api_key="sk-ant-...",
) as llm:
    response = llm.complete("Write a haiku")
    print(response.content)
# Automatically closes connection
```

### Parameter Overrides
```python
llm = OllamaLLM(model="llama3.2:3b", base_url="http://localhost:11434")

# Use different temperature for this specific request
response = llm.complete(
    "Generate creative story",
    temperature=0.9,  # Override default
    max_tokens=4096,  # Override default
)
```

## Error Handling Examples

```python
from src.agents.llm_providers import (
    create_llm_client,
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMAuthenticationError,
)

llm = create_llm_client(provider="openai", model="gpt-4", ...)

try:
    response = llm.complete("prompt")
except LLMAuthenticationError:
    # Handle invalid API key
    pass
except LLMRateLimitError:
    # Handle rate limiting (already retried internally)
    pass
except LLMTimeoutError:
    # Handle timeout (already retried internally)
    pass
except LLMError as e:
    # Handle other errors
    pass
```

## Performance Considerations

1. **Connection Pooling**: Uses httpx.Client with persistent connections
2. **Retry Logic**: Exponential backoff prevents overwhelming servers
3. **Timeout Configuration**: Prevents hanging requests
4. **Token Tracking**: Built-in token usage for cost monitoring
5. **Latency Measurement**: Tracks response time for all requests

## Security Considerations

1. **API Key Handling**: API keys passed securely via headers
2. **No Key Logging**: Raw responses stored but API keys never logged
3. **HTTPS Support**: Works with HTTPS endpoints (OpenAI, Anthropic)
4. **Timeout Protection**: Prevents resource exhaustion from hanging requests

## Future Enhancements (Out of Scope)

- Streaming support for real-time token generation
- Async/await support for concurrent requests
- Response caching for identical prompts
- Token budget management
- Request/response logging hooks
- Prometheus metrics integration
- Circuit breaker pattern for failing providers

## Integration Points

This implementation will be used by:
- `agents/` module for agent execution (task m2-04)
- `compiler/` module for LLM client instantiation
- `observability/` module for tracking LLM calls
- All agent configs that specify inference providers

## Notes

- All providers support parameter overrides at request time
- Token counting is provider-specific but normalized in response
- Retry logic only applies to retryable errors (not auth errors)
- Base class handles all HTTP communication and error mapping
- Provider implementations only define request/response format

## Testing

To run tests:
```bash
source venv/bin/activate
python -m pytest tests/test_agents/test_llm_providers.py -v
```

To test with a real Ollama instance:
```bash
# Start Ollama
ollama serve

# Run integration test (if implemented)
python -m pytest tests/test_agents/test_llm_providers.py -k integration
```
