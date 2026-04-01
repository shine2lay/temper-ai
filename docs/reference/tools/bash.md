[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Bash` Tool

[Back to Tools](index.md)

> Execute a shell command and return its output.

Security:
- Commands run in a subprocess with a clean environment
- workspace_root config constrains the working directory
- Configurable command allowlist (default: common safe commands)
- Timeout enforcement (default 30s, max 600s)

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | The shell command to execute |
| `timeout` | integer | No | Timeout in seconds (default 30, max 600) |

## Usage

Add `Bash` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Bash]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
