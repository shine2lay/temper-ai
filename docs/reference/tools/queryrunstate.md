[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `QueryRunState` Tool

[Back to Tools](index.md)

> Return the state of nodes in the current workflow run. Returns a JSON list of nodes with their status ('running', 'completed', 'failed') and, for completed nodes, their output and structured_output. Use this to discover what upstream nodes have produced before making decisions — e.g. before dispatching new work based on earlier agents' results. Outputs are truncated by default; pass truncate_chars=0 to disable.

Returns a list of nodes that have completed or are currently running in this
run, with their status, output, and structured output. Intended for agents
that need to decide what work to do based on what's already been produced —
e.g. a dispatcher agent that wants to see upstream research before emitting
a dispatch directive, or any agent that needs to consult prior-node output
that wasn't explicitly wired into its input_map.

Usage in agent config:
    tools: [QueryRunState]

The agent calls it like:
    QueryRunState()
    QueryRunState(node_names=["day_allocator"])
    QueryRunState(include_outputs=False, include_structured=True)

Returns JSON:
    [
      {"node_name": "day_allocator", "status": "completed",
       "output": "...", "structured_output": {...}},
      {"node_name": "tokyo_research", "status": "running"},
      ...
    ]

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `node_names` | array | No | Optional list of node names to return. Omit to return all. |
| `include_outputs` | boolean | No | Include truncated plain-text output. Default: true. |
| `include_structured` | boolean | No | Include parsed structured_output dicts. Default: true. |
| `truncate_chars` | integer | No | Maximum characters per node's output field before truncation. Default: 2000. Pass 0 to disable. |

## Usage

Add `QueryRunState` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [QueryRunState]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
