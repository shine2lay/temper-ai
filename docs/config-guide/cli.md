# CLI Commands

The `temper-ai` CLI is the primary interface for running, validating, and listing configurations.

**Binary:** `~/.local/bin/temper-ai`
**Source:** `temper_ai/cli/main.py`

> Always use `temper-ai` instead of `python -m` to avoid RuntimeWarning.

## Commands

### `temper-ai run` — Execute a Workflow

```bash
temper-ai run <workflow> [options]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `workflow` | Yes | Path to workflow YAML file |

**Options:**

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--input FILE` | | — | YAML file with input values |
| `--show-details` | `-d` | off | Real-time agent progress + post-execution report |
| `--dashboard [PORT]` | | — | Launch live web dashboard (default: 8420) |
| `--output FILE` | `-o` | — | Save results to JSON file |
| `--db PATH` | | `.meta-autonomous/observability.db` | Database path override |
| `--config-root DIR` | | `configs` | Config directory root |
| `--verbose` | `-v` | off | Enable DEBUG logging |

**Examples:**

```bash
# Basic run
temper-ai run configs/workflows/simple_research.yaml \
  --input examples/research_input.yaml

# With real-time details
temper-ai run configs/workflows/quick_decision_demo.yaml \
  --input examples/demo_input.yaml \
  --show-details

# Save output to file
temper-ai run configs/workflows/simple_research.yaml \
  --input examples/research_input.yaml \
  --output results.json

# With live dashboard
temper-ai run configs/workflows/llm_debate_demo.yaml \
  --input examples/debate_demo_input.yaml \
  --dashboard

# Dashboard on custom port
temper-ai run configs/workflows/llm_debate_demo.yaml \
  --input examples/debate_demo_input.yaml \
  --dashboard 9000

# Verbose logging
temper-ai run configs/workflows/simple_research.yaml \
  --input examples/research_input.yaml \
  -v
```

---

### `temper-ai validate` — Validate Config

```bash
temper-ai validate <workflow> [--config-root DIR]
```

Validates a workflow config without running it. Checks:
- Schema validation (Pydantic)
- Stage reference file existence
- Agent config file existence

**Example:**

```bash
temper-ai validate configs/workflows/quick_decision_demo.yaml
```

---

### `temper-ai serve --dev` — Dev Mode

```bash
temper-ai serve --dev [--port PORT] [--db PATH]
```

Starts the server in dev mode: no auth, permissive CORS, all routes enabled.
Replaces the former `temper-ai dashboard` command.

**Example:**

```bash
temper-ai serve --dev --port 8420
```

---

### `temper-ai list` — List Available Configs

```bash
temper-ai list workflows [--config-root DIR]
temper-ai list agents [--config-root DIR]
temper-ai list stages [--config-root DIR]
```

Lists available configuration files.

**Examples:**

```bash
temper-ai list workflows
temper-ai list agents
temper-ai list stages
```

---

## Available Demo Workflows

| Workflow | Input File | Description |
|----------|-----------|-------------|
| `configs/workflows/quick_decision_demo.yaml` | `examples/demo_input.yaml` | Fast 3-agent decision making |
| `configs/workflows/simple_research.yaml` | `examples/research_input.yaml` | Single-agent research |
| `configs/workflows/llm_debate_demo.yaml` | `examples/debate_demo_input.yaml` | Multi-round debate |
| `configs/workflows/technical_problem_solving.yaml` | `examples/technical_problem_demo_input.yaml` | 4-phase problem solving |
| `configs/workflows/collaborative_dialogue_demo.yaml` | `examples/dialogue_demo_input.yaml` | Multi-round collaborative dialogue |
| `configs/workflows/multi_agent_research.yaml` | `examples/market_research_input.yaml` | Parallel multi-agent research |
| `configs/workflows/erc721_generator.yaml` | — | Solidity contract generation |
