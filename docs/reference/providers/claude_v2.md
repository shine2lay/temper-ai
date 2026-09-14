[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `claude_v2` Provider

[Back to Providers](index.md)

Interactive, tmux-driven Claude Code. Drop-in BaseLLM, contract-parity
with the `claude` (v1) provider.

Why
---
From June 15, 2026 Anthropic meters `claude -p` and the Agent SDK against a
separate monthly credit (API rates, no rollover); *interactive* Claude Code
stays on the subscription. v2 drives the interactive TUI so temper's
automation rides subscription limits. v1 (`claude -p`, local/providers/
claude_code.py) stays as the metered/other-provider path; pick per agent via
`provider: claude` vs `provider: claude_v2`.

Design (validated 2026-05-30)
-----------------------------
- One FRESH `claude --session-id <uuid> --permission-mode bypassPermissions`
  per call, in its own tmux session. (`/clear` rotates the transcript file, so
  warm-session reuse can't yield a predictable, concurrency-safe filename —
  and fresh-per-call matches v1's cold-start-per-call cost model anyway.)
- tmux only injects the prompt and keeps the pane alive. The session
  transcript at ~/.claude/projects/<dashed-cwd>/<uuid>.jsonl is the source of
  truth for response text, token usage, and turn-completion. A fresh
  session-id means the file holds exactly this call's turn — no offset math.
- Turn done := a non-sidechain `assistant` row with stop_reason == "end_turn".
  Final text = that row's text blocks. Tokens = sum of message.usage across
  the turn's assistant rows. Cost = cache-aware compute (reuses pricing.py
  base rates), reported via raw_response.total_cost_usd like v1.

Contract parity with v1
-----------------------
complete()/stream() -> LLMResponse with content, prompt/completion/total
tokens, latency_ms, finish_reason, raw_response (incl. total_cost_usd).
tool_calls stays None — Claude Code runs tools internally, same as v1.
Honors kwargs already flattened by service.py from CallContext +
provider_config: model, cwd, session_id, execution_id, agent_name,
system_prompt_mode, and (via provider_config) allowed_tools, mcp_config,
max_budget_usd. No core interface change.

Lifecycle
---------
The provider owns the tmux lifecycle end-to-end: every call kills its own
session on exit; an import-time sweep reaps orphaned `claude_v2_<deadpid>_*`
sessions from crashed runs; an atexit hook kills this process's sessions on
normal exit. Concurrency is bounded by a global + per-token semaphore so the
OAuth request pattern reads as a heavy human user, not an automated fleet.

- **Default base URL:** `—`
- **Type:** HTTP-based (with automatic retry)

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | str | 'sonnet' | Model identifier |
| `timeout` | int | 300 | Request timeout in seconds |
| `cwd` | Optional[str] | None |  |
| `system_prompt_mode` | str | 'append' |  |
| `allowed_tools` | Optional[list[str]] | None |  |
| `mcp_config` | Optional[str] | None |  |
| `max_budget_usd` | Optional[float] | None |  |
| `base_url` | str | '' | API base URL |
| `api_key` | Optional[str] | None | API authentication key |

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
  provider: "claude_v2"
  model: "your-model-name"

# Or per-agent override:
agent:
  provider: "claude_v2"
  model: "your-model-name"
```

## Related

- [LLM Agent](../agents/llm.md) — agent type that calls providers
- [Budget Policy](../policies/budget.md) — tracks cumulative cost across calls
