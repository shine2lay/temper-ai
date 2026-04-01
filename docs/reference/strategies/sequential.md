[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | **Topology Strategies**

# `sequential` Strategy

[Back to Strategies](index.md)

Linear chain. Each agent depends on the previous.

Agent B receives Agent A's output via input_map: previous_output.

## YAML Example

```yaml
- name: pipeline
  type: stage
  strategy: sequential
  agents: [agents/draft, agents/edit, agents/polish]
```

## Related

- [Agent Types](../agents/index.md) — agents wired by this strategy
- [Tools](../tools/index.md) — tools agents can use within stages
