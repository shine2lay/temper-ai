[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Edit` Tool

[Back to Tools](index.md)

> Edit a file by exact string replacement. Pass several disjoint edits in one call — they are applied together or not at all. Each old_text must appear exactly once (include surrounding lines to make it unique) unless replace_all is set. Use Write to create a file or replace it wholesale.

Replaces FileEdit. The one behaviour worth porting from pi is `edits[]`: N
disjoint replacements applied in a single call, all-or-nothing. temper's
previous tool took one replacement per call, so a three-line change across a
file cost three round-trips — and with no prompt caching on the anthropic
provider, each round-trip resends the entire transcript. This is the cheapest
token saving available in the tool layer.

All-or-nothing matters as much as the batching: a half-applied set of edits
leaves the file in a state neither the agent nor the next node expects, and
the agent cannot tell which half landed.

Uniqueness is kept from both tools: `old_text` must match exactly once, unless
`replace_all` is set. The error names the count so the model knows to add
surrounding context rather than guess.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | File to edit. Relative paths resolve against the workspace. |
| `edits` | array | Yes | Replacements to apply together, in order. |

## Usage

Add `Edit` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Edit]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
