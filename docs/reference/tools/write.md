[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Write` Tool

[Back to Tools](index.md)

> Write content to a file, creating parent directories as needed. Overwrites by default; set append=true to add to the end instead. To change part of an existing file use Edit, which does not require rewriting the whole file.

Replaces FileWriter and FileAppend. Appending was never a separate capability,
only a mode, and two tools for one job cost a slot in every agent's tool list
and an occasional wrong choice.

Dropped from FileWriter on purpose: the `description` parameter, which injected
a comment/frontmatter header into the content. A write tool that silently edits
what you asked it to write is a surprise, and agents that want a header can put
one in `content`.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | File to write. Relative paths resolve against the workspace. |
| `content` | string | Yes | Content to write. |
| `append` | boolean | No | Append to the file instead of replacing it (default false). |
| `overwrite` | boolean | No | Allow replacing an existing file (default true). Ignored when append=true. |

## Usage

Add `Write` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Write]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
