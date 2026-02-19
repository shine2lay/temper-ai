# Temper AI

**A self-improving, fully observable autonomous agent system that can run entire product companies.**

## Vision

This framework enables AI agents to autonomously execute complete product lifecycles -- from market research to deployment to iterative improvement -- with minimal human intervention. The system learns from outcomes, experiments with approaches, and continuously optimizes itself.

See [VISION.md](./docs/VISION.md) for the complete vision.

## Current Status: Milestone 8 COMPLETE

**17 milestones complete (M1-M4, M5.1-M5.3, M6.1-M6.3, M7.1-M7.3, M8.1-M8.4).**

The autonomous self-improving loop is now functional: workflows can learn from their own execution, propose improvements, and auto-apply feedback.

## Architecture

```
temper_ai/
  workflow/        # LangGraph compiler/engine, config_loader, DAG/node builders
  stage/           # Stage compiler, executors (sequential, parallel, adaptive)
  agent/           # StandardAgent, BaseAgent, LLM providers, strategies
  llm/             # LLMService, cache, prompts, tool_keys
  tools/           # Tool registry, bash executor
  safety/          # Action policies, autonomy management, security
  observability/   # Execution tracker, metrics, collaboration tracker
  memory/          # Episodic, procedural, semantic memory with adapters
  learning/        # Pattern mining, recommendations, auto-tuning
  goals/           # Goal proposal, analysis, safety policy, review workflow
  portfolio/       # Multi-product orchestration, optimization, knowledge graph
  lifecycle/       # Self-modifying workflow adaptation
  experimentation/ # A/B testing, statistical analysis
  autonomy/        # Post-execution loop, feedback application, audit
  storage/         # Database models, schemas
  shared/          # Core utilities, constants, circuit breaker
  interfaces/      # CLI (temper-ai), dashboard, HTTP server

configs/
  agents/          # Agent definitions (YAML)
  stages/          # Stage definitions
  workflows/       # Workflow lifecycle definitions
  templates/       # Product type templates (web_app, api, data_pipeline, cli_tool)
  lifecycle/       # Lifecycle adaptation profiles
  portfolios/      # Portfolio configurations
```

## Key Features

1. **Radical Modularity** - Every component is swappable and configurable via YAML
2. **Full Observability** - Every decision traced and queryable (SQLite + OTEL)
3. **Autonomous Self-Improvement** - Post-execution learning loop mines patterns, proposes goals, applies feedback
4. **Progressive Autonomy** - 5-level trust system (Supervised to Strategic) with budget enforcement
5. **Multi-Agent Collaboration** - Parallel execution with consensus, debate, and merit-weighted strategies
6. **Multi-Layer Safety** - Composable policies, approval workflows, emergency stop, audit trail
7. **Portfolio Management** - Multi-product orchestration with knowledge graph and scorecards
8. **A/B Experimentation** - Statistical testing for workflow variants

## Quick Start

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Run a Workflow

```bash
# Simple workflow
temper-ai run configs/workflows/quick_decision_demo.yaml --input examples/demo_input.yaml --show-details

# With autonomous learning loop
temper-ai run configs/workflows/quick_decision_demo.yaml --input examples/demo_input.yaml --autonomous --show-details
```

### Validate a Workflow

```bash
temper-ai validate configs/workflows/quick_decision_demo.yaml --check-refs
```

### List Resources

```bash
temper-ai list workflows
temper-ai list agents
temper-ai list stages
```

### Autonomous Mode

Enable post-execution analysis via YAML or CLI flag:

```yaml
workflow:
  name: my_workflow
  autonomous_loop:
    enabled: true
    learning_enabled: true
    goals_enabled: true
    portfolio_enabled: true
```

Or: `temper-ai run workflow.yaml --autonomous`

See [Autonomous Mode Guide](./docs/guides/autonomous_mode.md) for details.

### Learning & Goals

```bash
temper-ai learning mine          # Mine patterns from execution history
temper-ai learning patterns      # View discovered patterns
temper-ai learning recommend     # Generate recommendations
temper-ai goals propose          # Propose improvement goals
temper-ai goals list             # List proposals
```

### Experimentation

```bash
temper-ai experiment list                    # List experiments
temper-ai experiment create --name X ...     # Create experiment
temper-ai experiment start <id>             # Start experiment
temper-ai experiment results <id>           # View analysis
```

### Templates

```bash
temper-ai template list                     # List product types
temper-ai template create --type api --name my-api  # Scaffold new project
```

### Dashboard

```bash
temper-ai dashboard                         # Launch web UI on port 8420
```

## Development

### Running Tests

```bash
source venv/bin/activate

# Run core tests (parallel)
python -m pytest tests/test_workflow/ tests/test_stage/ tests/test_agent/ tests/test_safety/ -n auto

# Run all tests
python -m pytest tests/ -n auto --ignore=tests/property --ignore=tests/self_improvement --ignore=tests/benchmarks --ignore=tests/test_benchmarks

# Quality check
python3 scripts/architecture_scan.py
```

### Code Quality

```bash
black .           # Format
ruff check .      # Lint
mypy temper_ai/   # Type check
```

## Milestone History

| Milestone | Description | Status |
|-----------|-------------|--------|
| M1 | Full observability infrastructure | Complete |
| M2 | Basic agent execution with LangGraph | Complete |
| M2.5 | Execution engine abstraction layer | Complete |
| M3 | Multi-agent collaboration strategies | Complete |
| M4 | Safety & governance system | Complete |
| M5.1 | Self-improvement foundation | Complete |
| M5.2 | Experimentation framework | Complete |
| M5.3 | Continuous learning | Complete |
| M6.1 | Progressive autonomy | Complete |
| M6.2 | Memory system | Complete |
| M6.3 | Multi-product templates | Complete |
| M7.1 | Self-modifying lifecycle | Complete |
| M7.2 | Strategic autonomy (goal proposals) | Complete |
| M7.3 | Portfolio management | Complete |
| M8.1 | Post-execution autonomous loop | Complete |
| M8.2 | Feedback application | Complete |
| M8.3 | Memory completion | Complete |
| M8.4 | Experimentation CLI + dashboard | Complete |

See [docs/milestones/](./docs/milestones/) for detailed retrospectives.

## Technology Stack

- **Execution Engine:** LangGraph (nested graphs for workflows and stages)
- **Configuration:** YAML with Pydantic validation
- **Database:** SQLModel + SQLAlchemy (SQLite dev, Postgres prod)
- **Console UI:** Rich library
- **Dashboard:** FastAPI + WebSocket
- **LLM Providers:** Multi-provider support (Ollama, vLLM, OpenAI, Anthropic)
- **Testing:** pytest + pytest-xdist (parallel)

## Documentation

- [Vision Document](./docs/VISION.md)
- [Autonomous Mode Guide](./docs/guides/autonomous_mode.md)
- [Feedback Loop Architecture](./docs/architecture/feedback_loop.md)
- [Configuration Guide](./docs/CONFIGURATION.md)
- [Milestone Retrospectives](./docs/milestones/)

## License

MIT License - See LICENSE file for details

---

**Built for the future of autonomous AI systems**
