[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Read` Tool

[Back to Tools](index.md)

> Read the contents of a text file. Output is capped at 2000 lines or 50KB (whichever comes first); when a file is longer the result ends with the offset to continue from. Use offset/limit to read a specific range instead of the whole file. Prefer this over running `cat` through Bash: that returns the entire file and can exhaust the context in one call.

temper had no file-reading tool: agents were told to shell out (`Bash("cat …")`),
which returns the whole file. One `cat` of a lock file, build log or minified
bundle is ~118k tokens — the entire 120k context window in a single tool result,
and with no prompt caching that cost is paid again on every following iteration.

Behaviour ported from pi's `read`, which solves this well:
- `offset`/`limit` for reading a slice
- a hard cap on lines AND bytes, whichever hits first
- a trailing line that tells the model exactly how to continue

That last part matters most for unattended agents: truncation the model can't
see is a trap, truncation that says "use offset=284 to continue" is a next step.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | File to read. Relative paths resolve against the workspace. |
| `offset` | integer | No | 1-indexed line to start from (default 1). |
| `limit` | integer | No | Maximum lines to return (default 2000). |

## Usage

Add `Read` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Read]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
