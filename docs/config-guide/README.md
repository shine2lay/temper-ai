# YAML Configuration Guide

Temper AI uses a **3-layer YAML hierarchy** to define multi-agent workflows:

```
Workflow  -->  Stage(s)  -->  Agent(s)
   |              |              |
 Pipeline      Execution      LLM + Prompt
 ordering      strategy       + Tools
```

Each layer is a separate `.yaml` file, connected by references. An optional **Tool** config layer and **Input** files round out the system.

```
configs/
├── workflows/    # Pipelines (what stages to run, in what order)
├── stages/       # Execution units (which agents, how they collaborate)
├── agents/       # Individual LLM agents (prompt, model, tools)
├── tools/        # Tool definitions (Calculator, search, etc.)
└── prompts/      # (Optional) External prompt templates
examples/         # Input files for workflows
```

## Sections

| Section | File | Description |
|---------|------|-------------|
| 1 | [agents.md](agents.md) | Agent configuration — LLM, prompts, tools, safety, memory |
| 2 | [stages.md](stages.md) | Stage configuration — execution modes, collaboration strategies, quality gates |
| 3 | [workflows.md](workflows.md) | Workflow configuration — pipelines, dependencies, budgets, error handling |
| 4 | [tools.md](tools.md) | Tool configuration — implementation, rate limits, safety checks |
| 5 | [inputs.md](inputs.md) | Input files — how to pass data into workflows |
| 6 | [cli.md](cli.md) | CLI commands — running, validating, listing configs |
| 7 | [variable-flow.md](variable-flow.md) | Variable flow — how data moves through the layers |
| 8 | [timeouts.md](timeouts.md) | Timeout hierarchy — how timeouts cascade |
| 9 | [security.md](security.md) | Security features — sandboxing, path validation, secrets |

## Quick Start

```bash
# Start the server
temper-ai serve --dev

# Run a workflow via the API
curl -X POST http://localhost:8420/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow": "workflows/simple_research.yaml", "inputs": {"query": "Research GraphQL vs REST"}}'

# Validate config
curl -X POST http://localhost:8420/api/validate \
  -d '{"workflow": "workflows/quick_decision_demo.yaml"}'

# List available workflows
curl http://localhost:8420/api/workflows/available
```
