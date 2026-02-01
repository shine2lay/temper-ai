# Meta-Autonomous Agent Framework

**A self-improving, fully observable autonomous agent system that can run entire product companies.**

## Vision

This framework enables AI agents to autonomously execute complete product lifecycles—from market research to deployment to iterative improvement—with minimal human intervention. The system learns from outcomes, experiments with approaches, and continuously optimizes itself.

See [META_AUTONOMOUS_FRAMEWORK_VISION.md](./docs/VISION.md) for the complete vision.

## Current Status: Milestone 4 ✅ COMPLETE - Ready for M5

**Latest Achievement:** Safety & Governance System - Full enterprise-grade safety controls for autonomous operation.

### Milestone 2 Deliverables ✅
- ✅ LLM provider abstraction (Ollama, OpenAI, Anthropic, vLLM)
- ✅ Tool registry with auto-discovery and execution
- ✅ Jinja2 prompt engine with template rendering
- ✅ StandardAgent implementation (LLM + tools)
- ✅ AgentFactory and BaseAgent interface
- ✅ LangGraph workflow compiler (YAML → executable graphs)
- ✅ Real-time console streaming visualization
- ✅ End-to-end integration tests (7/10 passing, 94 unit tests)

### Milestone 2.5 Deliverables ✅
- ✅ ExecutionEngine abstract interface (compile, execute, feature detection)
- ✅ CompiledWorkflow interface (invoke, ainvoke, metadata, visualization)
- ✅ LangGraphExecutionEngine adapter (wraps M2 compiler, 100% backward compatible)
- ✅ EngineRegistry for runtime engine selection
- ✅ Updated all imports to use abstraction layer
- ✅ Comprehensive documentation (architecture guide, custom engine tutorial)

**M2.5 Status:** Execution engine abstraction complete. Framework decoupled from LangGraph, ready for M5+ features.
**M2.5 ROI:** 1.5 days investment → 61.5 days saved on future migrations (41× return)
**See:** [Milestone 2.5 Completion Report](./docs/milestones/milestone2.5_completion.md) for full details.

### Milestone 3 Deliverables ✅ COMPLETE
- ✅ **Parallel Agent Execution** - 2-3x speedup with LangGraph nested subgraphs
- ✅ **Consensus Strategy** - Democratic majority voting with confidence tracking
- ✅ **Debate Strategy** - Multi-round debate with automatic convergence detection
- ✅ **Merit-Weighted Resolver** - Weight votes by agent expertise and success rate
- ✅ **Strategy Registry** - Pluggable strategy selection with automatic fallback
- ✅ **Convergence Detection** - Early termination when agents reach agreement
- ✅ **Collaboration Observability** - Track synthesis events, conflicts, convergence
- ✅ **Example Workflows** - Parallel research and debate decision demos
- ✅ **Comprehensive Documentation** - User guides and technical references
- ✅ **Multi-Agent State** - Shared state management for collaborative workflows
- ✅ **Configuration Schema** - YAML configuration for multi-agent workflows
- ✅ **Quality Gates** - Validation checkpoints for collaboration output
- ✅ **Adaptive Execution** - Dynamic strategy selection based on context
- ✅ **E2E Integration Tests** - Full workflow integration testing

**M3 Status:** Multi-agent collaboration system complete. Parallel execution delivers 2.25x speedup.
**Performance:** 3 agents sequential (45s) → parallel (20s) = 2.25x faster
**Test Coverage:** Full integration test suite passing
**See:** [Milestone 3 Completion Report](./docs/milestones/milestone3_completion.md) for full details.

### Milestone 4 Deliverables ✅ COMPLETE
- ✅ **PolicyComposer** - Compose and execute multiple safety policies in priority order
- ✅ **Safety Policies** - File access, secret detection, forbidden operations, rate limiting, blast radius
- ✅ **Approval Workflow** - Human-in-the-loop approvals for high-risk actions
- ✅ **Rollback Manager** - Snapshot and rollback mechanisms for safe experimentation
- ✅ **Circuit Breakers** - Automatic failure detection and recovery
- ✅ **Safety Gates** - Multi-layer safety validation checkpoints
- ✅ **Observability Integration** - Full safety event tracking and violation logging
- ✅ **Configuration System** - Flexible policy configuration and action mappings
- ✅ **Comprehensive Testing** - 60+ safety tests covering all policies and edge cases
- ✅ **Production Readiness** - Deployment guides and operational documentation

**M4 Status:** Enterprise-grade safety system complete. Ready for autonomous operation with full governance.
**Safety Coverage:** 11 implemented policies across 3 priority tiers (P0-P2)
**Test Coverage:** 60+ safety-specific tests passing
**See:** [Milestone 4 Completion Report](./docs/milestones/milestone4_completion.md) for full details.

## Architecture Overview

```
configs/          # YAML configurations
├── agents/       # Agent definitions
├── stages/       # Stage definitions
├── workflows/    # Workflow lifecycle definitions
├── tools/        # Tool configurations
├── prompts/      # Reusable prompt templates
└── triggers/     # Workflow activation triggers

src/
├── compiler/     # YAML → LangGraph compiler
├── agents/       # Agent implementations
├── tools/        # Tool implementations
├── strategies/   # Collaboration & conflict resolution
├── safety/       # Safety enforcement
├── observability/ # Tracing, logging, metrics
└── cli/          # Command-line interface
```

## Key Features

1. **Radical Modularity** - Every component is swappable and configurable
2. **Full Observability** - Every decision traced and queryable
3. **Self-Improvement Loop** - System learns from outcomes and optimizes itself
4. **Progressive Autonomy** - Earns trust gradually from supervised to autonomous
5. **Configuration as Code** - YAML-based workflow definitions
6. **Multi-Layer Safety** - Composable safety rules across tool/agent/stage/workflow

### M3 Multi-Agent Collaboration (New!)

**Parallel Execution:** Run multiple agents concurrently for 2-3x faster execution
- LangGraph nested subgraphs with concurrent branches
- Configurable max concurrent agents
- Automatic error handling and minimum success threshold

**Collaboration Strategies:** Synthesize agent outputs intelligently
- **Consensus** - Democratic majority voting (<10ms latency)
- **Debate** - Multi-round argumentation with convergence detection
- **Merit-Weighted** - Expert opinions weighted by success rate and domain expertise

**Conflict Resolution:** Automatic disagreement detection and resolution
- Primary strategy → Conflict resolver → Human escalation chain
- Configurable disagreement thresholds
- Merit-based weighting for expert tie-breaking

**Convergence Detection:** Stop debate early when agents reach agreement
- Automatic detection when 80% of agents unchanged
- Cost savings through early termination
- Higher confidence scores for converged decisions

**Example Usage:**
```yaml
# Parallel execution with consensus synthesis
execution:
  agent_mode: parallel
  max_concurrent: 3

collaboration:
  strategy: consensus
  conflict_resolver: merit_weighted
  config:
    threshold: 0.5
    conflict_threshold: 0.3
```

**Run Demo Workflows:**
```bash
# Parallel research (3 agents, consensus)
python examples/run_multi_agent_workflow.py parallel-research

# Debate decision (3 agents, multi-round debate)
python examples/run_multi_agent_workflow.py debate-decision
```

**Learn More:**
- [Multi-Agent Collaboration Guide](./docs/features/collaboration/multi_agent_collaboration.md)
- [Collaboration Strategies Reference](./docs/features/collaboration/collaboration_strategies.md)
- [M3 Examples](./examples/guides/multi_agent_collaboration_examples.md)

## Quick Start

### Prerequisites
- Python 3.11 or higher
- (Optional) Ollama for local LLMs
- (Optional) PostgreSQL for production observability

### Installation

1. **Clone the repository:**
```bash
# ⚠️ IMPORTANT: Replace 'yourusername' with the actual GitHub username/org before running
git clone https://github.com/yourusername/meta-autonomous-framework.git
cd meta-autonomous-framework
```

2. **Create virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies:**
```bash
# Note: Project uses pyproject.toml (setuptools auto-generates setup.py)
pip install -e ".[dev]"
```

4. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Run the demo:**
```bash
# Activate virtual environment
source venv/bin/activate

# Run Milestone 1 demo
python examples/milestone1_demo.py

# Run integration tests
pytest tests/integration/test_milestone1_e2e.py -v
```

### Running Your First Workflow

```bash
# Run a simple research workflow with Ollama
python examples/run_workflow.py configs/workflows/simple_research.yaml

# With custom input
python examples/run_workflow.py simple_research --prompt "Research Python typing benefits"

# Verbose output with result saving
python examples/run_workflow.py simple_research --verbose --output results.json
```

### Using the Execution Engine API

The framework uses an execution engine abstraction layer for flexible workflow execution:

```python
from src.compiler.engine_registry import EngineRegistry
from src.compiler.config_loader import ConfigLoader

# Load workflow config
loader = ConfigLoader()
config = loader.load_workflow("simple_research")

# Get engine from registry (default: langgraph)
registry = EngineRegistry()
engine = registry.get_engine_from_config(config)

# Compile workflow
compiled = engine.compile(config)

# Execute workflow
result = engine.execute(compiled, {"topic": "Python typing"})

# Access results
print(result["stage_outputs"])
```

**Select specific engine:**

```python
# Explicitly select LangGraph engine
engine = registry.get_engine("langgraph")

# Or specify engine in workflow YAML:
# workflow:
#   engine: langgraph
#   engine_config:
#     max_retries: 3
```

**Check engine capabilities:**

```python
# Feature detection for engine capabilities
if engine.supports_feature("convergence_detection"):
    print("Engine supports convergence detection for M5!")
else:
    print("Using basic execution mode")
```

See [Execution Engine Architecture](./docs/features/execution/execution_engine_architecture.md) for details.

## Development

### Project Structure

All Python packages have `__init__.py` files for proper imports.

### Running Tests

```bash
pytest
```

### Code Quality

```bash
# Format code
black .

# Lint
ruff check .

# Type check
mypy src/
```

## Documentation

- [Vision Document](./docs/VISION.md) - The ultimate vision and philosophy
- [Technical Specification](./TECHNICAL_SPECIFICATION.md) - Implementation details and schemas
- [Configuration Guide](./docs/CONFIGURATION.md) - How to configure agents, stages, workflows
- Observability Guide - Understanding traces and metrics (Coming soon)

## Technology Stack

- **Execution Engine:** LangGraph (nested graphs for workflows and stages)
- **Configuration:** YAML with Pydantic validation
- **Database:** SQLModel + SQLAlchemy (SQLite dev, Postgres prod)
- **Console UI:** Rich library
- **LLM Providers:** Multi-provider support (Ollama, vLLM, OpenAI, Anthropic)

## Contributing

This project is currently in early development (Milestone 1). Contributions will be welcome once core infrastructure is complete.

## License

MIT License - See LICENSE file for details

## Roadmap

- **Milestone 1:** Full observability infrastructure ✅ **COMPLETE**
- **Milestone 2:** Basic agent execution with LangGraph ✅ **COMPLETE**
- **Milestone 2.5:** Execution engine abstraction layer ✅ **COMPLETE** (1.5 days)
- **Milestone 3:** Multi-agent collaboration strategies ✅ **COMPLETE**
  - ✅ Parallel execution (2-3x speedup)
  - ✅ Consensus, debate, merit-weighted strategies
  - ✅ Convergence detection
  - ✅ Quality gates, adaptive execution, E2E tests
- **Milestone 4:** Safety & experimentation infrastructure ✅ **COMPLETE**
  - ✅ PolicyComposer and safety policies
  - ✅ Approval workflow and rollback manager
  - ✅ Circuit breakers and safety gates
- **Milestone 5:** Self-improvement loop ← **NEXT** (4 weeks)
- **Milestone 6:** Production-ready with multiple product types (4 weeks)

### Why M2.5 (Abstraction Layer)?

After specialist analysis, adding an abstraction layer over LangGraph now (at minimal coupling) will:
- **Prevent vendor lock-in** - Switch execution engines later with minimal effort (weeks vs months)
- **Enable M5+ features** - Convergence detection, self-modifying lifecycle, meta-circular execution
- **Support experimentation** - A/B test different engines in production
- **ROI: 41×** - 1.5 days investment saves 3-17 weeks on future migrations

**Cost to switch engines:**
- Without abstraction: 24 weeks at M6 (project-threatening)
- With abstraction: 6.5 weeks at M6 (manageable)

See [Milestone Roadmap](./docs/ROADMAP.md) for detailed timeline and tasks.

---

**Built with ❤️ for the future of autonomous AI systems**
