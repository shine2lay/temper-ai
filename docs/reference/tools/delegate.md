[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Delegate` Tool

[Back to Tools](index.md)

> Run one or more agents as sub-tasks. Each task specifies an agent name and inputs. Results are returned as JSON. Use this to delegate work to specialized agents and get their output back.

An agent calls Delegate like any other tool. The engine creates proper
agent nodes, runs them (with full observability), and returns results
to the calling agent's tool-calling loop.

Usage in agent config:
    tools: [Bash, FileWriter, Delegate]

The agent calls it like:
    Delegate(tasks=[
        {"agent": "implementer", "inputs": {"file": "Button.tsx", "task": "..."}},
        {"agent": "reviewer", "inputs": {"files": ["Button.tsx"]}},
    ])

Each task runs as a visible agent in the DAG. Results come back as JSON
so the calling agent can reason about them and delegate more work.

- **Modifies state:** Yes

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tasks` | array | Yes | List of tasks to delegate. Each task has 'agent' (agent config name) and 'inputs' (dict of input data for that agent). |

## Usage

Add `Delegate` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Delegate]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
