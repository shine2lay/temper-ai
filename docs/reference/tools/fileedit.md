[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `FileEdit` Tool

[Back to Tools](index.md)

> Replace exact text in an existing file. Provide the exact text to find (old_text) and what to replace it with (new_text). The old_text must match exactly once in the file, including whitespace and indentation. Include a few surrounding lines in old_text to make it unique. Use replace_all=true to replace all occurrences (e.g., renaming a variable).

Modeled after Claude Code's Edit tool: find an exact substring
in a file and replace it. The old_string must be unique in the
file (or use replace_all for bulk renames).

This is much more token-efficient than FileWriter for small changes —
the model only sends the changed fragment, not the entire file.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file_path` | string | Yes | Absolute path to the file to edit |
| `old_text` | string | Yes | The exact text to find (must be unique in the file) |
| `new_text` | string | Yes | The replacement text |
| `replace_all` | boolean | No | Replace all occurrences instead of requiring uniqueness (default: false) |

## Usage

Add `FileEdit` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [FileEdit]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
