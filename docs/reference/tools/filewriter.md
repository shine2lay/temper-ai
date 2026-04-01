[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `FileWriter` Tool

[Back to Tools](index.md)

> Write content to a file. Creates parent directories if needed.

Security:
- Path traversal protection (no .., no symlink escape)
- Forbidden paths (/etc, /sys, /proc, etc.)
- Configurable allowed_root constraint
- Content size limit (10MB)
- Overwrite protection (opt-in)

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | Yes | Path to the file to write |
| `content` | string | Yes | Content to write to the file |
| `overwrite` | boolean | No | Whether to overwrite if file exists (default true) |

## Usage

Add `FileWriter` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [FileWriter]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
