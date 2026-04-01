[Home](../index.md) | **Tools** | [LLM Providers](../providers/index.md) | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `Calculator` Tool

[Back to Tools](index.md)

> Evaluate a mathematical expression safely. Supports arithmetic, sqrt, sin, cos, tan, log, exp, abs, round, min, max, pi, e.

Uses AST whitelist approach — no eval(). Only allows arithmetic operations
and a small set of math functions.

- **Modifies state:** No (read-only)

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `expression` | string | Yes | Math expression to evaluate (e.g., '2 * (3 + 4)', 'sqrt(16)', 'sin(pi/2)') |

## Usage

Add `Calculator` to an [LLM agent](../agents/llm.md)'s tools list:

```yaml
agent:
  name: my_agent
  type: llm
  tools: [Calculator]
```

## Related

- [LLM Agent](../agents/llm.md) — agents that use tools
- [Safety Policies](../policies/index.md) — gate tool execution
