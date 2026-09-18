[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Glob` Tool

[Back to Tools](index.md)

> Find files by name pattern, e.g. '**/*.py' or 'src/**/test_*.ts'. Returns up to 200 paths (raise with limit), newest first. Skips anything the repo's .gitignore excludes, plus .git, node_modules, __pycache__, virtualenvs and build output. Use Grep to search file contents.

The counterpart to Grep (contents) and Read (one file): "what files are here?"
without `Bash("find …")`, whose output is unbounded and whose flags models get
wrong. Results are newest-first, because when an agent asks what exists it is
almost always looking for what it or a previous node just produced.

Named Glob rather than pi's `find`: the input is a glob pattern, and a tool
called `find` invites find(1) syntax (`-name`, `-type f`, `-exec`) — especially
next to a Bash tool that has the real find(1). It is also what Claude Code calls
it, so a prompt works unchanged under either provider.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | Yes | Glob pattern, e.g. '**/*.py'. |
| `path` | string | No | Directory to search in. Relative paths resolve against the workspace. Default: the workspace. |
| `limit` | integer | No | Maximum paths to return (default 200, max 2000). |
| `include_ignored` | boolean | No | Also return files excluded by .gitignore (default false). |

## Usage

Add `Glob` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Glob]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
