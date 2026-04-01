[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `openai` Provider

[Back to Providers](index.md)

Provider for OpenAI and OpenAI-compatible APIs.

Handles both completion and streaming via the /v1/chat/completions endpoint.
Works with OpenAI, Azure OpenAI, and any OpenAI-compatible API.

- **Default base URL:** `https://api.openai.com`
- **Type:** HTTP-based (with automatic retry)

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | — | Model identifier |
| `base_url` | str | — | API base URL |
| `api_key` | str | None | None | API authentication key |
| `temperature` | float | 0.7 | Sampling temperature (0.0-2.0) |
| `max_tokens` | int | 4096 | Maximum tokens in response |
| `timeout` | int | 120 | Request timeout in seconds |
| `max_retries` | int | 3 | Max retry attempts on transient failures |

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
  provider: "openai"
  model: "your-model-name"

# Or per-agent override:
agent:
  provider: "openai"
  model: "your-model-name"
```

## Related

- [LLM Agent](../agents/llm.md) — agent type that calls providers
- [Budget Policy](../policies/budget.md) — tracks cumulative cost across calls
