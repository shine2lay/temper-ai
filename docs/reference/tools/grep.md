[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Grep` Tool

[Back to Tools](index.md)

> Search file contents with a regular expression. Returns 'path:line: text' for up to 200 matches (raise with limit), then reports how many were omitted. Skips anything the repo's .gitignore excludes, plus .git, node_modules, __pycache__, virtualenvs and build output. Prefer this over running grep through Bash: that output is unbounded.

Agents previously searched with `Bash("grep -rn …")`, whose output is unbounded:
a pattern that matches a vendored directory or a lock file returns tens of
thousands of lines into the context. This returns `path:line: text` (pi's shape
— compact and unambiguous for a model to act on), capped, with a tail saying how
many matches were left behind so the agent can narrow the pattern rather than
assume it saw everything.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | Yes | Python regular expression. |
| `path` | string | No | File or directory to search. Relative paths resolve against the workspace. Default: the workspace. |
| `glob` | string | No | Only search files matching this glob, e.g. '*.py' or '**/*.ts'. |
| `ignore_case` | boolean | No | Case-insensitive match (default false). |
| `literal` | boolean | No | Treat pattern as plain text rather than a regular expression (default false). |
| `limit` | integer | No | Maximum matches to return (default 200, max 2000). |
| `include_ignored` | boolean | No | Also search files excluded by .gitignore (default false). |

## Usage

Add `Grep` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Grep]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
