[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | **Topology Strategies**

# Topology Strategies Reference

_Auto-generated from code. Do not edit manually._

**4 built-in strategies** define how agents within a stage are wired together.

Strategies are **not** a separate execution layer — they generate a node topology that the graph executor runs like any other graph.

Each strategy takes a list of [agent](../agents/index.md) configs and produces a DAG. Agents within a strategy can use [tools](../tools/index.md) and are subject to [safety policies](../policies/index.md).

| Name | Description |
|------|-------------|
| [`debate`](debate.md) | Multi-round debate. N debaters speak per round seeing the previous |
| [`leader`](leader.md) | Workers run in parallel, leader synthesizes their outputs. |
| [`parallel`](parallel.md) | All agents run independently. No depends_on between them. |
| [`sequential`](sequential.md) | Linear chain. Each agent depends on the previous. |

## Extending

```python
from temper_ai.stage.topology import register_topology
from temper_ai.stage.agent_node import AgentNode

def debate_topology(agent_configs, config):
    """Agents debate in rounds until consensus."""
    # Return list of AgentNodes with depends_on wiring
    ...

register_topology("debate", debate_topology)
```
