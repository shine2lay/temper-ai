[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `openai` Provider

[Back to Providers](index.md)

Provider for OpenAI and OpenAI-compatible APIs.

Two credentials, two wire protocols. An API key goes to
``/v1/chat/completions`` on ``base_url`` (this class, and its Ollama and
vLLM subclasses, which never see an OAuth token). A ChatGPT-subscription
OAuth token goes to the Codex Responses endpoint through
``CodexTransport``; ``complete``/``stream`` delegate to it and the rest of
this class is bypassed.

Handles both completion and streaming via the /v1/chat/completions endpoint.
Works with OpenAI, Azure OpenAI, and any OpenAI-compatible API.

- **Default base URL:** `https://api.openai.com`
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
