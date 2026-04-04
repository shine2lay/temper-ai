[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | **Topology Strategies**

# `sequential` Strategy

[Back to Strategies](index.md)

Linear chain. Each agent depends on the previous.

Each agent receives the full parent input_data plus an auto-injected
``other_agents`` field containing its predecessor's output. No input_map
is set so that parent-level fields (e.g. workspace_path) flow through.

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
