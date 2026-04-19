[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `RemoveNode` Tool

[Back to Tools](index.md)

> Remove a still-pending node from the running workflow graph. Called during an agent's run when the agent determines a downstream node shouldn't execute (e.g., a placeholder that turned out unnecessary). The target is marked SKIPPED; any further-downstream nodes whose input_map refs it will cascade to skipped too. Only pending nodes can be removed — already-started nodes are unaffected.

Lets an LLM agent mark a still-pending node in the running DAG for skip.
Downstream nodes that referenced the removed node's output cascade to
skipped (standard engine behavior for unresolved input_map refs).

Usage in agent config:
    tools: [RemoveNode]

Agent calls it during its run:
    RemoveNode(target="placeholder_research")

The tool buffers the op into ExecutionContext.dispatch_state.pending_ops
alongside any AddNode calls from the same run. After the agent completes,
the executor drains the buffer and applies ops atomically.

Only nodes that haven't started running yet can be removed. Removing an
already-completed or running node is a no-op (it's already past the point
of cancellation).

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `target` | string | Yes | Name of the pending node to remove. Must exist in the current DAG and not yet have started. |

## Usage

Add `RemoveNode` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [RemoveNode]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
