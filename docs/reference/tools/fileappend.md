[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `FileAppend` Tool

[Back to Tools](index.md)

> Append text to the end of a file. The file must already exist. Use this instead of FileWriter when you want to add a new section to an existing file without rewriting it.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | Yes | Absolute path to the file to append to |
| `content` | string | Yes | Text to append at the end of the file |

## Usage

Add `FileAppend` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [FileAppend]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
