# Collaboration Strategies Reference (M3)

Complete reference for all M3 collaboration strategies, conflict resolvers, and configuration options.

---

## Table of Contents

1. [Strategy Overview](#strategy-overview)
2. [ConsensusStrategy](#consensusstrategy)
3. [DebateAndSynthesize](#debateandsynthesiz)
4. [MeritWeightedResolver](#meritweightedresolver)
5. [HumanEscalationResolver](#humanescalationresolver)
6. [Strategy Selection Guide](#strategy-selection-guide)
7. [Custom Strategies](#custom-strategies)

---

## Strategy Overview

| Strategy | Type | Rounds | Use Case | Complexity |
|----------|------|--------|----------|------------|
| **Consensus** | Synthesis | 1 | Quick decisions, clear majority | Low |
| **DebateAndSynthesize** | Synthesis | 1-N | High-stakes, complex decisions | High |
| **MeritWeighted** | Conflict Resolver | 1 | Expert opinions, weighted voting | Medium |
| **HumanEscalation** | Conflict Resolver | N/A | Irreconcilable conflicts | N/A |

### Strategy Pattern

All strategies implement the `CollaborationStrategy` interface:

```python
from temper_ai.strategies.base import CollaborationStrategy, AgentOutput, SynthesisResult

class MyStrategy(CollaborationStrategy):
    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize agent outputs into unified decision."""
        pass

    def get_capabilities(self) -> Dict[str, bool]:
        """Return strategy capabilities."""
        return {
            "supports_debate": False,
            "supports_convergence": False,
            "supports_merit_weighting": False,
        }
```

---

## ConsensusStrategy

**File**: `temper_ai/strategies/consensus.py`

### Description

Democratic majority voting with confidence tracking. Simplest and fastest strategy.

### Algorithm

```
1. Count votes for each decision
2. Find majority decision (>50% of votes)
3. Calculate confidence:
   - Consensus strength = majority_size / total_agents
   - Avg confidence = mean(supporter_confidences)
   - Final confidence = consensus_strength × avg_confidence
4. Detect conflicts if disagreement > threshold
```

### Configuration

```yaml
collaboration:
  strategy: consensus
  config:
    threshold: 0.5  # Majority threshold (0-1)
    require_unanimous: false  # Require 100% agreement?
    conflict_threshold: 0.3  # Flag conflicts if disagreement >30%
```

### Python API

```python
from temper_ai.strategies.consensus import ConsensusStrategy
from temper_ai.strategies.base import AgentOutput

strategy = ConsensusStrategy()

outputs = [
    AgentOutput("agent1", "Option A", "reason1", 0.9, {}),
    AgentOutput("agent2", "Option A", "reason2", 0.8, {}),
    AgentOutput("agent3", "Option B", "reason3", 0.7, {})
]

result = strategy.synthesize(outputs, {"threshold": 0.5})

print(result.decision)  # "Option A"
print(result.confidence)  # ~0.57
print(result.votes)  # {"Option A": 2, "Option B": 1}
```

### Capabilities

```python
{
    "supports_debate": False,
    "supports_convergence": False,
    "supports_merit_weighting": False,
    "supports_partial_participation": True,
    "deterministic": True
}
```

### Performance

- **Time Complexity**: O(n) where n = number of agents
- **Space Complexity**: O(k) where k = number of unique decisions
- **Typical Latency**: <10ms

### Edge Cases

| Case | Behavior |
|------|----------|
| **Tie (2-2 split)** | Returns None, escalates to conflict resolver |
| **Single agent** | Returns that agent's decision with 100% confidence |
| **All disagree** | Returns most confident agent's decision, flags conflict |
| **Unanimous** | Returns with 100% consensus + avg confidence |

---

## DebateAndSynthesize

**File**: `temper_ai/strategies/debate.py`

### Description

Multi-round structured debate with convergence detection. Produces highest-quality decisions through iterative argumentation.

### Algorithm

```
1. Round 1: Agents state initial positions
2. For each round (up to max_rounds):
   a. Share all arguments with all agents
   b. Agents refine positions based on others' arguments
   c. Calculate convergence = unchanged_agents / total
   d. If convergence >= threshold: STOP (converged)
   e. If round == max_rounds: STOP (max reached)
3. Extract consensus from final round
4. Build detailed reasoning from debate history
```

### Configuration

```yaml
collaboration:
  strategy: debate_and_synthesize
  config:
    max_rounds: 3  # Maximum debate rounds
    convergence_threshold: 0.8  # Stop if 80% unchanged
    min_rounds: 1  # Minimum rounds (even if converged)
    require_unanimous: false  # Require 100% agreement
    debate_structure: round_robin  # Turn-taking structure
```

### Python API

```python
from temper_ai.agent.strategies.multi_round import MultiRoundStrategy

strategy = MultiRoundStrategy(mode="debate")

# Initial positions
outputs_r1 = [
    AgentOutput("a1", "Microservices", "reason1", 0.7, {}),
    AgentOutput("a2", "Monolith", "reason2", 0.8, {}),
    AgentOutput("a3", "Hybrid", "reason3", 0.6, {})
]

result = strategy.synthesize(outputs_r1, {
    "max_rounds": 3,
    "convergence_threshold": 0.8
})

print(result.decision)  # Final consensus
print(result.metadata["total_rounds"])  # Rounds executed
print(result.metadata["converged"])  # True/False
print(result.metadata["convergence_round"])  # Round of convergence
```

### Debate History Structure

```python
{
    "rounds": [
        {
            "round_number": 0,
            "convergence_score": 0.0,  # First round
            "new_insights": True,
            "decision_distribution": {"A": 2, "B": 1}
        },
        {
            "round_number": 1,
            "convergence_score": 0.67,  # 2/3 unchanged
            "new_insights": True,
            "decision_distribution": {"A": 3}
        }
    ],
    "total_rounds": 2,
    "converged": True,
    "convergence_round": 1
}
```

### Capabilities

```python
{
    "supports_debate": True,
    "supports_convergence": True,
    "supports_merit_weighting": False,  # Not yet (M4+)
    "requires_conflict_resolver": True,
    "deterministic": False  # Depends on agent responses
}
```

### Performance

- **Time Complexity**: O(n × r) where n = agents, r = rounds
- **Space Complexity**: O(n × r) for debate history
- **Typical Latency**: 3-10x single-round (depends on LLM)

### Edge Cases

| Case | Behavior |
|------|----------|
| **No convergence** | Returns majority from last round, confidence penalized |
| **Early unanimous** | Terminates after min_rounds |
| **Agent failure mid-debate** | Continues with remaining agents |
| **All agents flip-flop** | Runs to max_rounds, flags instability |

### Cost Optimization

```yaml
# Minimize cost while maintaining quality
config:
  max_rounds: 2  # Lower rounds
  min_rounds: 1  # Don't force extra rounds
  convergence_threshold: 0.7  # Lower threshold (easier to converge)
  early_termination: true  # Stop ASAP
```

---

## MeritWeightedResolver

**File**: `temper_ai/strategies/merit_weighted.py`

### Description

Conflict resolver that weights votes by agent merit (expertise, success rate, recency). Expert opinions carry more weight.

### Algorithm

```
1. Load agent merits from observability database
2. Calculate composite merit for each agent:
   merit = (domain_merit × 0.4) +
           (overall_merit × 0.3) +
           (recent_performance × 0.3)
3. Weight each vote: vote_weight = merit × confidence
4. Sum weights per decision
5. Select decision with highest total weight
6. Calculate confidence:
   - If >85%: auto-resolve
   - If <50%: escalate
   - Otherwise: flag for review
```

### Merit Components

| Component | Weight | Description |
|-----------|--------|-------------|
| **Domain Merit** | 40% | Success rate in current domain |
| **Overall Merit** | 30% | Global success rate across all tasks |
| **Recent Performance** | 30% | Time-decayed recent task success |

### Configuration

```yaml
collaboration:
  strategy: consensus
  conflict_resolver: merit_weighted
  config:
    merit_weights:
      domain_merit: 0.4
      overall_merit: 0.3
      recent_performance: 0.3
    auto_resolve_threshold: 0.85  # Auto if >85% weighted
    escalation_threshold: 0.5  # Escalate if <50%
    recency_decay_days: 30  # 50% decay after 30 days
```

### Python API

```python
from temper_ai.strategies.merit_weighted import MeritWeightedResolver
from temper_ai.strategies.conflict_resolution import AgentMerit, ResolutionContext

resolver = MeritWeightedResolver(config={
    "auto_resolve_threshold": 0.85,
    "escalation_threshold": 0.5
})

# Set up context with merit scores
context = ResolutionContext(
    agent_merits={
        "expert": AgentMerit("expert", 0.9, 0.85, 0.9, "expert"),
        "novice": AgentMerit("novice", 0.6, 0.65, 0.6, "novice")
    },
    agent_outputs={
        "expert": AgentOutput("expert", "A", "reason", 0.9, {}),
        "novice": AgentOutput("novice", "B", "reason", 0.8, {})
    },
    stage_name="research",
    workflow_name="mvp"
)

resolution = resolver.resolve(conflict, context)
print(resolution.decision)  # "A" (expert wins)
print(resolution.confidence)  # ~0.76
```

### Capabilities

```python
{
    "requires_merit": True,  # Needs merit scores
    "requires_human": False,
    "requires_llm": False,
    "supports_partial_context": True,
    "deterministic": True  # Same merit → same result
}
```

### Performance

- **Time Complexity**: O(n) where n = number of agents
- **Space Complexity**: O(n) for merit lookups
- **Typical Latency**: <20ms (includes DB query)

---

## HumanEscalationResolver

**File**: `temper_ai/strategies/merit_weighted.py`

### Description

Fallback resolver that escalates irreconcilable conflicts to human decision-makers.

### Behavior

Always raises `RuntimeError` with escalation message. In M4+, will integrate with approval workflow system.

### Python API

```python
from temper_ai.strategies.merit_weighted import HumanEscalationResolver

resolver = HumanEscalationResolver()

try:
    resolution = resolver.resolve(conflict, context)
except RuntimeError as e:
    print(e)  # "Human escalation required: ..."
    # In M4: Send to approval workflow
```

---

## Strategy Selection Guide

### Decision Tree

```
START: Need to synthesize agent outputs

Q: Is this a time-critical decision?
├─ YES: Use Consensus (fast, simple)
└─ NO: Continue

Q: Is this a high-stakes decision?
├─ YES: Use Debate (quality over speed)
└─ NO: Use Consensus

Q: Do agents have different expertise levels?
├─ YES: Use Consensus + MeritWeighted resolver
└─ NO: Use Consensus

Q: Are conflicts common?
├─ YES: Use Debate (reduces conflicts)
└─ NO: Use Consensus
```

### Recommendation Matrix

| Scenario | Strategy | Conflict Resolver |
|----------|----------|-------------------|
| **Quick research** | Consensus | MeritWeighted |
| **Architecture decision** | Debate | HumanEscalation |
| **Expert panel** | Consensus | MeritWeighted |
| **Routine analysis** | Consensus | None |
| **Critical infrastructure** | Debate | HumanEscalation |
| **User research** | Consensus | None |

---

## Custom Strategies

### Creating a Custom Strategy

```python
# my_custom_strategy.py
from temper_ai.strategies.base import CollaborationStrategy, SynthesisResult
from typing import List, Dict, Any

class WeightedAverageStrategy(CollaborationStrategy):
    """Custom strategy: weighted average of confidence scores."""

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        # Validate inputs
        self.validate_inputs(agent_outputs)

        # Custom logic: weight by confidence
        weighted_votes = {}
        for output in agent_outputs:
            decision = str(output.decision)
            weighted_votes[decision] = weighted_votes.get(decision, 0) + output.confidence

        # Pick highest weighted
        decision = max(weighted_votes, key=weighted_votes.get)
        confidence = weighted_votes[decision] / len(agent_outputs)

        # Detect conflicts
        conflicts = self.detect_conflicts(agent_outputs, threshold=0.3)

        from temper_ai.strategies.base import calculate_vote_distribution
        votes = calculate_vote_distribution(agent_outputs)

        return SynthesisResult(
            decision=decision,
            confidence=confidence,
            method="weighted_average",
            votes=votes,
            conflicts=conflicts,
            reasoning=f"Weighted by confidence: {weighted_votes}",
            metadata={"weighted_votes": weighted_votes}
        )

    def get_capabilities(self) -> Dict[str, bool]:
        return {
            "supports_debate": False,
            "supports_convergence": False,
            "supports_merit_weighting": True,
            "deterministic": True
        }
```

### Registering Custom Strategy

```python
# Register with strategy registry
from temper_ai.strategies.registry import StrategyRegistry

registry = StrategyRegistry()
registry.register("weighted_average", WeightedAverageStrategy)
```

### Using Custom Strategy

```yaml
# In stage config
collaboration:
  strategy: weighted_average
  config:
    # Custom config options
```

---

## API Reference

### AgentOutput

```python
@dataclass
class AgentOutput:
    agent_name: str
    decision: Any
    reasoning: str
    confidence: float  # 0.0 to 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### SynthesisResult

```python
@dataclass
class SynthesisResult:
    decision: Any
    confidence: float  # 0.0 to 1.0
    method: str
    votes: Dict[str, int]
    conflicts: List[Conflict]
    reasoning: str
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Conflict

```python
@dataclass
class Conflict:
    agents: List[str]
    decisions: List[Any]
    disagreement_score: float  # 0.0 to 1.0
    context: Dict[str, Any] = field(default_factory=dict)
```

---

## Troubleshooting

### "Strategy not found: xyz"

**Solution**: Check strategy name spelling, or register custom strategy.

### "Merit scores not available"

**Solution**: Ensure observability DB has merit data, or use fallback strategy.

### "Debate did not converge"

**Solution**: Lower convergence_threshold or increase max_rounds.

---

**Document Version**: 1.0
**Created**: 2026-01-26
**Author**: m3-16-documentation
