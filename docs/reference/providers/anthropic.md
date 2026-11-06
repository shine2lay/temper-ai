[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `anthropic` Provider

[Back to Providers](index.md)

Provider for Anthropic Claude models.

Uses the anthropic Python SDK. Requires: pip install anthropic

Key differences from OpenAI:
- System prompt is a separate parameter, not in messages array
- Tool results use content blocks (tool_use/tool_result), not tool_calls
- Response has content[] array with text and tool_use blocks

Credentials
-----------
The provider accepts two kinds of credential and tells them apart by
prefix. An API key (``sk-ant-api…``) is sent as ``x-api-key``. An OAuth
access token (``sk-ant-oat…``) is sent as a bearer token, which is how the
Anthropic SDK itself carries OAuth credentials (``auth_token=``).

Resolution order: an explicit ``api_key`` argument, then
``ANTHROPIC_API_KEY``, then pi's own Claude logins. The API key wins when
it is set, because it is this provider's native credential.

Several subscriptions, one cache
-------------------------------
Without an API key the provider uses pi's Claude logins: the pi slots the
pools file lists (``pools.logins.slots``, e.g. ``anthropic``,
``anthropic-2``; see ``temper_ai.llm.pi_logins`` and docs/pools.md). Temper
holds no login of its own: each call asks temper-pi-host for its slot's
current login, good for the call's timeout, and keeps it for that call only.
The slot list is read again on each call, so a slot taken out of the file is
never picked again, without a restart; the provider itself comes up only when
the file lists at least one slot at start. When the helper can't be reached the
call fails at once, naming it; there is no other source.

The slots are separate subscriptions with separate rate-limit windows. The
pool rotates *between* agents and never *within* one — an agent's calls in a
given run all go out on the same slot, because Anthropic's prompt cache is per
account and a tool-using run re-sends its transcript every iteration. A slot
that answers 429 is cooled until its reset and the call is retried on another;
the sticky agent then loses its warm cache, which is why failover is a fallback
and not the normal path. A slot whose login pi refuses is cooled for a while
and the call goes on another. See ``temper_ai.llm.token_pool``.

A call can instead name its slot (``token: anthropic-2``). It then goes out on
that slot only: a limit there is not retried on another account but raised as
``TokenCooling``, and the agent's fallback list says where to go next.

Anthropic treats a bare bearer request from a third-party client
differently from one that identifies as its own tooling. What identification
to send — if any — is a policy decision that does not belong in this file.
It is delegated to an *OAuth request shaper* registered at startup
(``register_oauth_shaper``): it may add headers to, and rewrite, each
outgoing request. It is consulted per request, so registration order does
not matter. Without one, OAuth requests go out unshaped and the provider
says so once.

- **Default base URL:** `https://api.anthropic.com`
- **Type:** SDK-based (uses official SDK)

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | 'claude-sonnet-4-5-20250929' | Model identifier |
| `api_key` | str | None | None | API authentication key |
| `base_url` | str | 'https://api.anthropic.com' | API base URL |
| `temperature` | float | 0.7 | Sampling temperature (0.0-2.0) |
| `max_tokens` | int | 32000 | Maximum tokens in response |
| `timeout` | int | 120 | Request timeout in seconds |
| `cache_ttl` | str | '5m' |  |
| `effort` | str | None | None |  |
| `thinking_budget` | int | None | None |  |
| `stream_retry_budget_s` | float | 600.0 | Seconds of waiting, in all, before a call whose stream broke mid-answer (an overload, an API error, a stalled read) fails; it is sent again after 1, 2, 4, 8, 16, 32 s, then every 60 s. 0 sends it once only |

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
