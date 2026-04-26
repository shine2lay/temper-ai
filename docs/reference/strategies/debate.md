[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | **Topology Strategies**

# `debate` Strategy

[Back to Strategies](index.md)

Multi-round debate. N debaters speak per round seeing the previous
round's transcripts; a synthesizer reads the whole debate and produces
the unified output.

Synthesizer is identified by `role: synthesizer` on the agent config.
Default: last agent in the list. All others are debaters.

Topology for D debaters × R rounds (with R=3 here):

    round 1:  d1__r1, d2__r1, d3__r1     no deps, run in parallel
    round 2:  d1__r2, d2__r2, d3__r2     each depends on ALL of round 1
    round 3:  d1__r3, d2__r3, d3__r3     each depends on ALL of round 2
    final:    synth                       depends on ALL nodes (every round)

Each debater node from round 2 onwards receives the previous round's
transcripts via `_strategy_context` (the renderer surfaces this as
`{{ other_agents }}` in the agent's task_template). Round-1 debaters
have no `_strategy_context` so the template's else branch fires —
they produce an opening position.

The synthesizer depends on every debate node so its `_strategy_context`
contains the full transcript across all rounds, labeled per node
(`[d1__r1]: ...`, `[d1__r2]: ...`, etc.).

strategy_config:
    rounds: int (default 3) — number of debate rounds; must be >= 1

## YAML Example

```yaml
- name: my_stage
  type: stage
  strategy: debate
  agents: [agents/a, agents/b]
```

## Related

- [Agent Types](../agents/index.md) — agents wired by this strategy
- [Tools](../tools/index.md) — tools agents can use within stages
