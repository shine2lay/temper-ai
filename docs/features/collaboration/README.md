# Multi-Agent Collaboration Features

Documentation for M3 multi-agent collaboration system.

## Features

### [Multi-Agent Collaboration Overview](./multi_agent_collaboration.md)
**Purpose:** Complete guide to multi-agent collaboration capabilities

**Topics Covered:**
- System architecture and design principles
- Parallel vs sequential execution modes
- Collaboration strategy framework
- Observability and tracking
- Configuration and usage examples
- Performance characteristics

**Key Concepts:**
- **Parallel Execution**: Run multiple agents simultaneously (2-3x speedup)
- **Strategy Pattern**: Pluggable collaboration strategies
- **Synthesis Layer**: Combine agent outputs into unified decisions
- **Convergence Detection**: Early termination when agents agree

**Use Cases:**
- Research tasks requiring multiple perspectives
- Decision-making with weighted votes
- Quality improvement through debate
- Complex problem-solving with specialist agents

---

### [Collaboration Strategies](./collaboration_strategies.md)
**Purpose:** Detailed guide to each collaboration strategy implementation

**Strategies Documented:**

1. **Voting Strategy**
   - Democratic majority voting
   - Confidence-weighted votes
   - Tie-breaking mechanisms
   - Best for: Quick decisions with clear options

2. **Consensus Strategy**
   - Agreement threshold detection
   - Similarity scoring between outputs
   - Iterative refinement
   - Best for: Research tasks, complex analysis

3. **Debate Strategy**
   - Multi-round argumentation
   - Automatic convergence detection
   - Position evolution tracking
   - Best for: Challenging assumptions, exploring trade-offs

4. **Hierarchical Strategy**
   - Reviewer-worker pattern
   - Quality gating and approval
   - Escalation paths
   - Best for: Code review, content validation

5. **Merit-Weighted Resolver**
   - Agent expertise tracking
   - Success rate weighting
   - Dynamic weight adjustment
   - Best for: Leveraging specialist knowledge

**Custom Strategy Development:**
- Extend `CollaborationStrategy` interface
- Implement `synthesize()` method
- Register with strategy registry
- Add configuration schema
- Write tests

---

## Architecture

### Component Structure
```
CollaborationStrategy (interface)
  ├─ VotingStrategy
  ├─ ConsensusStrategy
  ├─ DebateStrategy
  ├─ HierarchicalStrategy
  └─ MeritWeightedResolver

StrategyRegistry
  └─ register/resolve strategies

ParallelExecutor
  └─ execute agents in parallel

SynthesisLayer
  └─ combine agent outputs
```

### Data Flow
```
Input Task
  ↓
Strategy Selection
  ↓
Parallel Agent Execution
  ↓
Output Collection
  ↓
Synthesis (via Strategy)
  ↓
Unified Result
```

### Observability
All collaboration events tracked:
- Agent executions (parallel timing)
- Vote/consensus calculations
- Debate rounds and convergence
- Synthesis decisions
- Conflict resolutions

---

## Configuration

### Basic Configuration
```yaml
# configs/workflows/research.yaml
collaboration:
  strategy: voting
  min_votes: 3
  confidence_threshold: 0.7
```

### Advanced Configuration
```yaml
collaboration:
  strategy: debate
  max_rounds: 5
  convergence_threshold: 0.8
  fallback_strategy: consensus

  strategies:
    debate:
      position_tracking: true
      allow_position_change: true

    consensus:
      similarity_threshold: 0.75
      min_agreement: 2
```

### Strategy Composition
```yaml
collaboration:
  strategy: merit_weighted
  fallback_chain:
    - merit_weighted
    - consensus
    - voting

  merit_config:
    track_success: true
    decay_rate: 0.1
```

---

## Performance

### Parallel Execution Speedup
- **Sequential**: 3 agents × 15s each = 45s total
- **Parallel**: max(15s, 15s, 15s) = 15s total
- **Speedup**: 3x faster

### Overhead Costs
- Strategy synthesis: <100ms
- Convergence detection: <50ms
- Observability tracking: <20ms per agent

### Scaling Characteristics
- Linear scaling up to CPU core count
- Network-bound for distributed execution
- Memory usage: O(n) where n = number of agents

---

## Examples

### Research Collaboration
```python
from src.compiler import WorkflowCompiler

workflow = WorkflowCompiler.from_file("configs/workflows/research.yaml")
result = workflow.execute({
    "task": "Research TypeScript adoption trends",
    "collaboration": {
        "strategy": "consensus",
        "agents": ["researcher_web", "researcher_academic", "researcher_industry"]
    }
})
```

### Decision Making
```python
result = workflow.execute({
    "decision": "Choose authentication method",
    "options": ["OAuth2", "JWT", "Session"],
    "collaboration": {
        "strategy": "voting",
        "agents": ["security_expert", "ux_expert", "backend_expert"]
    }
})
```

### Code Review
```python
result = workflow.execute({
    "code": pull_request_diff,
    "collaboration": {
        "strategy": "hierarchical",
        "workers": ["code_reviewer_1", "code_reviewer_2"],
        "reviewer": "senior_architect"
    }
})
```

---

## Testing

See collaboration strategy tests:
- `tests/test_collaboration/test_strategies.py` - Unit tests for each strategy
- `tests/integration/test_parallel_execution.py` - Parallel execution tests
- `tests/integration/test_debate_workflow.py` - Multi-round debate tests

---

## Related Documentation

- [Execution Features](../execution/) - Workflow execution and engines
- [Observability Features](../observability/) - Tracking and visualization
- [Core Interfaces](../../interfaces/core/) - Agent, Tool, LLM interfaces
- [Milestone 3 Report](../../milestones/milestone3_completion.md) - M3 completion details
