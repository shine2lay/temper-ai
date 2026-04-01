[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `gemini` Provider

[Back to Providers](index.md)

Provider for Google Gemini models.

Uses the google-genai Python SDK. Requires: pip install google-genai

Key differences from OpenAI:
- Uses generateContent API with Part objects
- Tool calling uses FunctionDeclaration, not OpenAI function format
- Response has candidates[].content.parts[]

- **Default base URL:** `https://generativelanguage.googleapis.com`
- **Type:** SDK-based (uses official SDK)

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | 'gemini-2.5-flash' | Model identifier |
| `api_key` | str | None | None | API authentication key |
| `base_url` | str | 'https://generativelanguage.googleapis.com' | API base URL |
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
  provider: "gemini"
  model: "your-model-name"

# Or per-agent override:
agent:
  provider: "gemini"
  model: "your-model-name"
```

## Related

- [LLM Agent](../agents/llm.md) — agent type that calls providers
- [Budget Policy](../policies/budget.md) — tracks cumulative cost across calls
