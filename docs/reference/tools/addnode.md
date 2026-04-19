[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `AddNode` Tool

[Back to Tools](index.md)

> Add a new node to the running workflow graph. Called during an agent's run to dispatch follow-up work conditionally (use when the decision can't be expressed as a declarative Jinja template over your output). The new node is queued and inserted into the DAG atomically after your agent completes, alongside any `dispatch:` block from your config. Safety caps (max_children_per_dispatch, max_dispatch_depth, etc.) apply to the merged batch.

Lets an LLM agent add a new node to the running workflow DAG by calling
a typed tool, as opposed to the tier 1 declarative `dispatch:` block in
the agent YAML. Useful when the decision to dispatch is conditional in a
way that a Jinja-over-output template can't express.

Usage in agent config:
    tools: [AddNode]

Agent calls it during its run:
    AddNode(
        name="investigate_spike",
        agent="log_investigator",
        depends_on=["parent_agent"],
        input_map={"log_window": "parent_agent.structured.window"}
    )

The tool buffers the op into ExecutionContext.dispatch_state.pending_ops,
keyed by the agent's node_path. After the agent completes, the executor
drains the buffer, merges with any declarative dispatch ops, and applies
them atomically — same cap enforcement, same validation as tier 1.

Out of scope for v1:
    - Subgraph-in-one-call (agents compose subgraphs via multiple AddNode
      calls with depends_on wiring)
    - `replace_node` — compose via RemoveNode + AddNode

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Unique name for the new node. Must not collide with any existing node in the current DAG. |
| `type` | `agent` \| `stage` | No | Node type. Defaults to 'agent' when `agent` is set, 'stage' when `agents` is set. |
| `agent` | string | No | Name of the agent config to run (for type=agent). Must match a registered agent. |
| `agents` | array | No | List of agent names to run inside a stage (for type=stage). |
| `strategy` | `parallel` \| `sequential` | No | For type=stage — how to run the agents. |
| `depends_on` | array | No | Names of nodes this new node depends on. Can reference any pending or already-completed node in the DAG. |
| `input_map` | object | No | Map of local input name → source ref (e.g. 'upstream_node.output' or 'upstream_node.structured.field'). Same format as static workflow input_map. |

## Usage

Add `AddNode` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [AddNode]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
