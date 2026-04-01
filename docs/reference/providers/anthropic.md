[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `anthropic` Provider

[Back to Providers](index.md)

Provider for Anthropic Claude models.

Uses the anthropic Python SDK. Requires: pip install anthropic

Key differences from OpenAI:
- System prompt is a separate parameter, not in messages array
- Tool results use content blocks (tool_use/tool_result), not tool_calls
- Response has content[] array with text and tool_use blocks

- **Default base URL:** `https://api.anthropic.com`
- **Type:** SDK-based (uses official SDK)

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | 'claude-sonnet-4-20250514' | Model identifier |
| `api_key` | str | None | None | API authentication key |
| `base_url` | str | 'https://api.anthropic.com' | API base URL |
| `temperature` | float | 0.7 | Sampling temperature (0.0-2.0) |
| `max_tokens` | int | 4096 | Maximum tokens in response |
| `timeout` | int | 120 | Request timeout in seconds |

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
  provider: "anthropic"
  model: "your-model-name"

# Or per-agent override:
agent:
  provider: "anthropic"
  model: "your-model-name"
```

## Related

- [LLM Agent](../agents/llm.md) — agent type that calls providers
- [Budget Policy](../policies/budget.md) — tracks cumulative cost across calls
