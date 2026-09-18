[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `vllm` Provider

[Back to Providers](index.md)

vLLM provider — OpenAI-compatible with vLLM extras.

vLLM exposes an OpenAI-compatible API. This provider adds:
- chat_template_kwargs (e.g., disable thinking mode for Qwen models)
- stream_options for usage stats in streaming mode

- **Default base URL:** `http://localhost:8000`
- **Type:** HTTP-based (with automatic retry)

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
  provider: "vllm"
  model: "your-model-name"

# Or per-agent override:
agent:
  provider: "vllm"
  model: "your-model-name"
```

## Related

- [LLM Agent](../agents/llm.md) — agent type that calls providers
- [Budget Policy](../policies/budget.md) — tracks cumulative cost across calls
