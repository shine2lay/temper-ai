[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | **Topology Strategies**

# `parallel` Strategy

[Back to Strategies](index.md)

All agents run independently. No depends_on between them.

The graph executor detects they're independent and runs them concurrently.

## YAML Example

```yaml
- name: code
  type: stage
  strategy: parallel
  agents: [agents/coder_a, agents/coder_b, agents/coder_c]
```

## Related

- [Agent Types](../agents/index.md) — agents wired by this strategy
- [Tools](../tools/index.md) — tools agents can use within stages
