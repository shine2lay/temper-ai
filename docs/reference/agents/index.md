[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | **Agent Types** | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# Agent Types Reference

_Auto-generated from code. Do not edit manually._

Temper AI includes **2 agent types**. Set `type:` in your agent YAML config.

| Name | Description |
|------|-------------|
| [`llm`](llm.md) | Agent that uses LLM with Jinja2 prompt templates, tools, and memory. |
| [`script`](script.md) | Agent that executes a Jinja-rendered bash script. |

## Extending

```python
from temper_ai.agent import register_agent_type
from temper_ai.agent.base import AgentABC
from temper_ai.shared.types import AgentResult, ExecutionContext

class MyAgent(AgentABC):
    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        ...

register_agent_type("my_agent", MyAgent)
```
