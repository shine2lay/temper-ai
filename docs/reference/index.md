# Temper AI — Reference Documentation

_Auto-generated from code. Do not edit manually._

## Modules

- [Tools](tools/index.md) — Built-in tools agents can use (Bash, FileWriter, Http, etc.)
- [LLM Providers](providers/index.md) — LLM provider integrations (OpenAI, vLLM, Ollama, Anthropic, Gemini)
- [Agent Types](agents/index.md) — Agent type implementations (LLM agent, Script agent)
- [Safety Policies](policies/index.md) — Safety policies for action enforcement (file access, budget, forbidden ops)
- [Topology Strategies](strategies/index.md) — Stage topology strategies (parallel, sequential, leader)

## How It Fits Together

```
Workflow YAML
  |-- nodes (agent or stage)
  |     |-- agent config --- type -------- agents/
  |     |                 |-- provider ---- providers/
  |     |                 +-- tools ------- tools/
  |     +-- stage config --- strategy ---- strategies/
  +-- safety --- policies ----------------- policies/
```

1. A **workflow** defines a graph of nodes.
2. Each **agent node** runs an [agent type](agents/index.md) with a configured [LLM provider](providers/index.md) and optional [tools](tools/index.md).
3. Each **stage node** uses a [topology strategy](strategies/index.md) to wire agents together.
4. [Safety policies](policies/index.md) enforce constraints on every action.

## Quick Example

```yaml
workflow:
  name: my_workflow
  defaults:
    provider: "vllm"
    model: "qwen3-next"
  safety:
    policies:
      - type: budget
        max_cost_usd: 5.00
  nodes:
    - name: plan
      type: agent
      agent: planner

    - name: code
      type: stage
      strategy: parallel
      agents: [coder_a, coder_b]
      depends_on: [plan]

    - name: review
      type: agent
      agent: reviewer
      depends_on: [code]
```
