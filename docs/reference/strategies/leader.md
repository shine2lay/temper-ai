[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | **Topology Strategies**

# `leader` Strategy

[Back to Strategies](index.md)

Workers run in parallel, leader synthesizes their outputs.

Leader is identified by role: leader in config. Default: last agent.
Workers' outputs are combined into leader's _strategy_context.

## YAML Example

```yaml
- name: review
  type: stage
  strategy: leader
  agents:
    - agents/security_reviewer
    - agents/quality_reviewer
    - agent: agents/decider
      role: leader  # receives all workers' outputs
```

## Related

- [Agent Types](../agents/index.md) — agents wired by this strategy
- [Tools](../tools/index.md) — tools agents can use within stages
