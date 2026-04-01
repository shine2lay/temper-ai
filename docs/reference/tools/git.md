[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `git` Tool

[Back to Tools](index.md)

> Run git commands in the workspace (status, diff, add, commit, push, etc.)

Provides a structured interface for common git commands.
All operations are scoped to the workspace directory.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | Git subcommand and arguments (e.g., 'status', 'diff --staged', 'add .') |

## Config Options

These are set via the tool config dict, not YAML.

| Option | Type | Default |
|--------|------|---------|
| `workspace` | str | None | None |
| `timeout` | int | 30 |

## Usage

Add `git` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [git]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
