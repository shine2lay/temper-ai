[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `ollama` Provider

[Back to Providers](index.md)

Provider for Ollama (local models via OpenAI-compatible API).

Ollama exposes an OpenAI-compatible endpoint at /v1/chat/completions.
This provider extends OpenAILLM with Ollama-specific defaults.

No API key required. Default base URL: http://localhost:11434

- **Default base URL:** `http://localhost:11434`
- **Type:** HTTP-based (with automatic retry)

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | 'llama3.2' | Model identifier |
| `base_url` | str | 'http://localhost:11434' | API base URL |

## Provider Interface

Methods this provider implements:

### `_build_request()`

Build the provider-specific request payload.

### `_parse_response()`

Parse provider response into LLMResponse.

### `_get_headers()`

Return provider-specific headers.

### `_get_endpoint()`

Return the API endpoint path (e.g., '/v1/chat/completions').

### `_consume_stream()`

Consume a streaming response, calling on_chunk for each delta.

## Usage

```yaml
# In workflow defaults:
defaults:
  provider: "ollama"
  model: "your-model-name"

# Or per-agent override:
agent:
  provider: "ollama"
  model: "your-model-name"
```

## Related

- [LLM Agent](../agents/llm.md) — agent type that calls providers
- [Budget Policy](../policies/budget.md) — tracks cumulative cost across calls
