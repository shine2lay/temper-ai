# M3 Multi-Agent Workflow Examples

This directory contains example workflows demonstrating M3 multi-agent collaboration features.

## Overview

M3 introduces true multi-agent collaboration with:
- **Parallel Execution**: Multiple agents execute concurrently
- **Collaboration Strategies**: Consensus, Debate, Merit-Weighted Resolution
- **Convergence Detection**: Automatically detect when agents reach agreement
- **Quality Gates**: Validate outputs before proceeding
- **Comprehensive Observability**: Track all collaboration events

## Available Examples

### 1. Parallel Multi-Agent Research

**File**: `configs/workflows/multi_agent_research.yaml`

Demonstrates 3 agents executing research tasks in parallel and synthesizing results via consensus voting.

**Agents**:
- Market Researcher: Analyzes market trends
- Competitor Researcher: Analyzes competitive landscape
- User Researcher: Analyzes user needs

**M3 Features**:
- Parallel agent execution
- Consensus synthesis
- Conflict detection
- Min successful agents enforcement

**Run**:
```bash
python examples/run_multi_agent_workflow.py parallel-research
```

**Use Cases**:
- Comprehensive market research
- Multi-perspective analysis
- Parallel data gathering

---

### 2. Debate-Based Decision Making

**File**: `configs/workflows/debate_decision.yaml`

Demonstrates multi-round structured debate with convergence detection.

**Agents**:
- Advocate: Argues for the proposal
- Skeptic: Challenges and questions
- Analyst: Provides objective analysis

**M3 Features**:
- Multi-round debate
- Convergence detection
- Position tracking
- Early termination on convergence

**Run**:
```bash
python examples/run_multi_agent_workflow.py debate-decision
```

**Use Cases**:
- Architecture decisions
- Technology selection
- Strategic planning
- Any decision requiring deep reasoning

---

## Running Examples

### Prerequisites

1. **Ollama installed and running**:
   ```bash
   ollama serve
   ollama pull llama3.2:3b
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize database** (first time only):
   ```python
   from src.observability.database import init_database
   init_database("sqlite:///observability.db")
   ```

### List Available Workflows

```bash
python examples/run_multi_agent_workflow.py --list
```

### Run Specific Workflow

```bash
python examples/run_multi_agent_workflow.py parallel-research
python examples/run_multi_agent_workflow.py debate-decision
```

## Output

Each workflow produces:

1. **Console Output**: Real-time progress and results
2. **Gantt Chart (HTML)**: Interactive visualization of execution timeline
3. **Console Gantt**: ASCII timeline printed to terminal
4. **Database Records**: Full execution trace in SQLite database

## Configuration Files

### Workflows
- `configs/workflows/multi_agent_research.yaml`
- `configs/workflows/debate_decision.yaml`

### Stages
- `configs/stages/parallel_research_stage.yaml`
- `configs/stages/debate_stage.yaml`

### Agents
Uses existing `configs/agents/simple_researcher.yaml` with different roles.

## Customization

### Change Number of Agents

Edit the stage YAML file:

```yaml
agents:
  - name: agent1
    config_path: configs/agents/simple_researcher.yaml
    role: role1
  - name: agent2
    config_path: configs/agents/simple_researcher.yaml
    role: role2
  # Add more agents...
```

### Change Collaboration Strategy

```yaml
collaboration:
  strategy: consensus  # or debate_and_synthesize, merit_weighted
  config:
    threshold: 0.5
    require_unanimous: false
```

### Adjust Parallel Execution

```yaml
execution:
  agent_mode: parallel  # or sequential
  max_concurrent: 3

error_handling:
  min_successful_agents: 2  # Minimum required for success
```

### Configure Debate Rounds

```yaml
collaboration:
  strategy: debate_and_synthesize
  config:
    max_rounds: 3
    convergence_threshold: 0.8
    min_rounds: 1
```

## Performance Expectations

### Parallel Research (3 agents)
- **Sequential Time**: ~45 seconds (3 agents × 15 seconds)
- **Parallel Time**: ~20 seconds (overhead + max agent time)
- **Speedup**: ~2.25x

### Debate Decision (3 agents, 2 rounds)
- **Time**: ~40-60 seconds (depends on convergence)
- **Rounds**: 1-3 (early termination if converged)

## Troubleshooting

### "Module not found" errors
```bash
export PYTHONPATH=/path/to/meta-autonomous-framework
```

### "Ollama connection refused"
```bash
ollama serve  # Start Ollama server
```

### "Database not initialized"
```python
from src.observability.database import init_database
init_database("sqlite:///observability.db")
```

### "Strategy registry not found"
The implementation includes a fallback to simple consensus if registry is unavailable.

## Next Steps

1. **Try modifying inputs**: Change research topics or decision prompts
2. **Experiment with thresholds**: Adjust convergence and confidence thresholds
3. **Add more agents**: Scale up to 5-10 agents
4. **Create custom agents**: Design agents with specialized system prompts
5. **Combine strategies**: Use parallel execution + debate for complex decisions

## Learn More

- [M3 Technical Specification](../TECHNICAL_SPECIFICATION.md)
- [Collaboration Strategies](../src/strategies/README.md)
- [Configuration Guide](../docs/CONFIGURATION.md)
- [Observability Guide](../docs/OBSERVABILITY.md)

## Contributing

Found a bug or want to add more examples? See [CONTRIBUTING.md](../CONTRIBUTING.md).

---

**Created by**: m3-14-example-workflows
**Date**: 2026-01-26
**Milestone**: M3 - Multi-Agent Collaboration
