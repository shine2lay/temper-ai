[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `claude_code` Provider

[Back to Providers](index.md)

Provider that shells out to the Claude Code CLI.

Uses the `claude` CLI in headless mode (-p). Claude Code manages its own
tool-calling loop (Bash, file ops, search, web) so `complete()` returns the
final result with no tool_calls for the LLMService to chase.

Runs on your Max plan by default — no API key needed.

Usage in agent YAML:
    agent:
      name: my_coder
      provider: claude_code
      model: haiku          # sonnet (default), opus, haiku

- **Default base URL:** `—`
- **Type:** HTTP-based (with automatic retry)

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | 'sonnet' | Model identifier |
| `allowed_tools` | list[str] | None | None |  |
| `max_budget_usd` | float | None | None |  |
| `timeout` | int | 300 | Request timeout in seconds |
| `cwd` | str | None | None |  |
| `mcp_config` | str | None | None |  |
| `base_url` | str | '' | API base URL |
| `api_key` | str | None | None | API authentication key |

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
  provider: "claude_code"
  model: "your-model-name"

# Or per-agent override:
agent:
  provider: "claude_code"
  model: "your-model-name"
```

## Related

- [LLM Agent](../agents/llm.md) — agent type that calls providers
- [Budget Policy](../policies/budget.md) — tracks cumulative cost across calls
