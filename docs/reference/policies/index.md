[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | **Safety Policies** | [Topology Strategies](../strategies/index.md)

# Safety Policies Reference

_Auto-generated from code. Do not edit manually._

Temper AI includes **3 built-in safety policies**. Configure them in your workflow YAML under `safety.policies`.

Policies are evaluated with **first-deny-wins** semantics: if any policy denies an action, it is blocked regardless of other policies.

Policies gate [tool](../tools/index.md) execution — every tool call passes through the policy engine before running.

| Name | Description |
|------|-------------|
| [`budget`](budget.md) | Enforce cost and token limits for a workflow run. |
| [`file_access`](file_access.md) | Restrict file operations to allowed paths and block denied paths. |
| [`forbidden_ops`](forbidden_ops.md) | Block shell commands matching dangerous patterns. |

## Extending

Implement `BasePolicy` and register it. It will be evaluated on every [tool](../tools/index.md) call matching its `action_types`.

```python
from temper_ai.safety import register_policy
from temper_ai.safety.base import BasePolicy, ActionType, PolicyDecision

class MyPolicy(BasePolicy):
    action_types = [ActionType.TOOL_CALL]

    def evaluate(self, action_type, action_data, context) -> PolicyDecision:
        return PolicyDecision(action="allow", reason="ok", policy_name=self.name)

register_policy("my_policy", MyPolicy)
```
