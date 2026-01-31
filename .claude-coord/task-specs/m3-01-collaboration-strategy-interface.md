# Task: m3-01-collaboration-strategy-interface - Create Collaboration Strategy Interface

**Priority:** CRITICAL (P0)
**Effort:** 6 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Create abstract base class for collaboration strategies that define how multiple agents synthesize their outputs into a unified decision. This is the foundation interface for all M3 multi-agent collaboration patterns.

---

## Files to Create

- `src/strategies/base.py` - CollaborationStrategy ABC and related types (~200 lines)
- `tests/test_strategies/test_base.py` - Interface tests

---

## Acceptance Criteria

### Core Functionality
- [ ] `CollaborationStrategy` ABC with `synthesize(agent_outputs, config) -> SynthesisResult` method
- [ ] `SynthesisResult` dataclass with decision, confidence, votes, conflicts fields
- [ ] `AgentOutput` dataclass to standardize agent results
- [x] - [ ] `get_capabilities() -> Dict[str, bool]` method for feature detection
- [x] - [ ] `get_metadata() -> Dict[str, Any]` method for strategy info
- [x] - [ ] All methods properly decorated with `@abstractmethod`

### Type Safety
- [x] - [ ] Full type hints for all parameters and return types
- [ ] Pydantic models or dataclasses for all data structures
- [x] - [ ] Runtime validation of agent_outputs format

### Documentation
- [x] - [ ] Complete docstrings with examples for all classes and methods
- [ ] Usage examples in module docstring
- [ ] Design rationale documented

### Testing
- [x] - [ ] Test CollaborationStrategy cannot be instantiated directly (raises TypeError)
- [x] - [ ] Test SynthesisResult dataclass construction
- [x] - [ ] Test AgentOutput dataclass validation
- [ ] Test abstract method enforcement

---

## Implementation Details

### Class Structure

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum


class SynthesisMethod(Enum):
    """Methods for combining agent outputs."""
    CONSENSUS = "consensus"
    WEIGHTED_MERGE = "weighted_merge"
    BEST_OF = "best_of"
    DEBATE_EXTRACT = "debate_extract"
    HIERARCHICAL = "hierarchical"


@dataclass
class AgentOutput:
    """Standardized agent output format.

    Attributes:
        agent_name: Name of agent that produced output
        decision: Agent's primary decision/output
        reasoning: Agent's reasoning/justification
        confidence: Agent's confidence score (0-1)
        metadata: Additional metadata (tokens, cost, duration, etc.)
    """
    agent_name: str
    decision: Any  # Primary output/decision
    reasoning: str  # Why this decision?
    confidence: float  # 0-1 confidence score
    metadata: Dict[str, Any]  # Tokens, cost, duration, etc.

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


@dataclass
class Conflict:
    """Represents disagreement between agents.

    Attributes:
        agents: List of agents involved in conflict
        decisions: Conflicting decisions
        disagreement_score: Measure of disagreement severity (0-1)
        context: Additional context about conflict
    """
    agents: List[str]
    decisions: List[Any]
    disagreement_score: float  # 0=minor, 1=severe
    context: Dict[str, Any]


@dataclass
class SynthesisResult:
    """Result of synthesizing multiple agent outputs.

    Attributes:
        decision: Final synthesized decision
        confidence: Confidence in synthesis (0-1)
        method: Method used for synthesis
        votes: Vote counts per decision option
        conflicts: List of conflicts detected
        reasoning: Explanation of how decision was reached
        metadata: Additional info (rounds, convergence, etc.)
    """
    decision: Any
    confidence: float
    method: str  # Which synthesis method used
    votes: Dict[str, int]  # Vote counts
    conflicts: List[Conflict]  # Conflicts detected
    reasoning: str  # How decision was reached
    metadata: Dict[str, Any]  # Rounds, convergence, participation, etc.

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


class CollaborationStrategy(ABC):
    """Abstract base class for multi-agent collaboration strategies.

    Collaboration strategies define how multiple agents' outputs
    are synthesized into a unified decision. Different strategies
    implement different collaboration patterns:
    - Consensus: Majority voting
    - Debate: Multi-round argumentation
    - Merit-weighted: Weight by agent merit
    - Hierarchical: Lead agent decides

    Example:
        >>> strategy = ConsensusStrategy()
        >>> outputs = [
        ...     AgentOutput("agent1", "Option A", "Because...", 0.9, {}),
        ...     AgentOutput("agent2", "Option A", "I agree...", 0.8, {}),
        ...     AgentOutput("agent3", "Option B", "But...", 0.7, {})
        ... ]
        >>> result = strategy.synthesize(outputs, {})
        >>> result.decision
        'Option A'
        >>> result.confidence
        0.85
    """

    @abstractmethod
    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize multiple agent outputs into unified decision.

        Args:
            agent_outputs: List of outputs from all agents
            config: Strategy-specific configuration

        Returns:
            SynthesisResult with decision, confidence, conflicts

        Raises:
            ValueError: If agent_outputs is empty or invalid
            RuntimeError: If synthesis fails
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, bool]:
        """Get strategy capabilities.

        Returns:
            Dict of capability flags:
            - supports_debate: Multi-round debate
            - supports_convergence: Convergence detection
            - supports_merit_weighting: Uses agent merit scores
            - supports_partial_participation: Can handle missing agents
            - supports_async: Can run asynchronously
        """
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """Get strategy metadata.

        Returns:
            Strategy metadata:
            - name: Strategy name
            - version: Strategy version
            - description: Brief description
            - config_schema: Expected config format
        """
        return {
            "name": self.__class__.__name__,
            "version": "1.0",
            "description": self.__doc__ or "",
            "config_schema": {}
        }

    def validate_inputs(self, agent_outputs: List[AgentOutput]) -> None:
        """Validate agent outputs before synthesis.

        Args:
            agent_outputs: Outputs to validate

        Raises:
            ValueError: If validation fails
        """
        if not agent_outputs:
            raise ValueError("agent_outputs cannot be empty")

        if not all(isinstance(o, AgentOutput) for o in agent_outputs):
            raise ValueError("All outputs must be AgentOutput instances")

        # Check for duplicate agent names
        agent_names = [o.agent_name for o in agent_outputs]
        if len(agent_names) != len(set(agent_names)):
            raise ValueError("Duplicate agent names detected")

    def detect_conflicts(
        self,
        agent_outputs: List[AgentOutput],
        threshold: float = 0.3
    ) -> List[Conflict]:
        """Detect conflicts between agent decisions.

        Args:
            agent_outputs: Outputs to check for conflicts
            threshold: Disagreement threshold (0-1)

        Returns:
            List of detected conflicts
        """
        conflicts = []

        # Group by decision
        decision_groups: Dict[str, List[AgentOutput]] = {}
        for output in agent_outputs:
            decision_key = str(output.decision)
            if decision_key not in decision_groups:
                decision_groups[decision_key] = []
            decision_groups[decision_key].append(output)

        # If >2 decision groups, we have conflicts
        if len(decision_groups) > 1:
            disagreement_score = 1.0 - (max(len(g) for g in decision_groups.values()) / len(agent_outputs))

            if disagreement_score >= threshold:
                conflicts.append(Conflict(
                    agents=[o.agent_name for o in agent_outputs],
                    decisions=list(decision_groups.keys()),
                    disagreement_score=disagreement_score,
                    context={
                        "num_decisions": len(decision_groups),
                        "largest_group": max(len(g) for g in decision_groups.values())
                    }
                ))

        return conflicts


# Utility functions for common operations

def calculate_consensus_confidence(
    agent_outputs: List[AgentOutput],
    decision: Any
) -> float:
    """Calculate confidence based on consensus strength.

    Args:
        agent_outputs: All agent outputs
        decision: The consensus decision

    Returns:
        Confidence score (0-1)
    """
    # Get agents supporting this decision
    supporters = [o for o in agent_outputs if o.decision == decision]

    if not supporters:
        return 0.0

    # Consensus strength: percentage of agents
    consensus_strength = len(supporters) / len(agent_outputs)

    # Average confidence of supporters
    avg_confidence = sum(o.confidence for o in supporters) / len(supporters)

    # Combined confidence
    return consensus_strength * avg_confidence


def extract_majority_decision(agent_outputs: List[AgentOutput]) -> Any:
    """Extract majority decision from agent outputs.

    Args:
        agent_outputs: All agent outputs

    Returns:
        Most common decision (None if tie)
    """
    from collections import Counter

    decisions = [o.decision for o in agent_outputs]
    counts = Counter(decisions)

    if not counts:
        return None

    # Get most common
    most_common = counts.most_common(2)

    # Check for tie
    if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
        return None  # Tie, needs tiebreaker

    return most_common[0][0]
```

---

## Test Strategy

### Unit Tests (`tests/test_strategies/test_base.py`)

```python
import pytest
from src.strategies.base import (
    CollaborationStrategy,
    AgentOutput,
    SynthesisResult,
    Conflict,
    calculate_consensus_confidence,
    extract_majority_decision
)


def test_collaboration_strategy_is_abstract():
    """CollaborationStrategy cannot be instantiated directly."""
    with pytest.raises(TypeError):
        CollaborationStrategy()


def test_agent_output_validation():
    """Test AgentOutput validation."""
    # Valid output
    output = AgentOutput(
        agent_name="test",
        decision="yes",
        reasoning="because",
        confidence=0.9,
        metadata={}
    )
    assert output.confidence == 0.9

    # Invalid confidence
    with pytest.raises(ValueError, match="Confidence must be 0-1"):
        AgentOutput("test", "yes", "because", 1.5, {})


def test_synthesis_result_validation():
    """Test SynthesisResult validation."""
    result = SynthesisResult(
        decision="yes",
        confidence=0.85,
        method="consensus",
        votes={"yes": 2, "no": 1},
        conflicts=[],
        reasoning="Majority voted yes",
        metadata={}
    )
    assert result.confidence == 0.85

    # Invalid confidence
    with pytest.raises(ValueError):
        SynthesisResult("yes", 1.2, "consensus", {}, [], "test", {})


def test_detect_conflicts():
    """Test conflict detection."""
    class MockStrategy(CollaborationStrategy):
        def synthesize(self, agent_outputs, config):
            pass
        def get_capabilities(self):
            return {}

    strategy = MockStrategy()
    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "yes", "r2", 0.8, {}),
        AgentOutput("a3", "no", "r3", 0.7, {})
    ]

    conflicts = strategy.detect_conflicts(outputs, threshold=0.3)
    assert len(conflicts) == 1
    assert conflicts[0].disagreement_score > 0


def test_calculate_consensus_confidence():
    """Test consensus confidence calculation."""
    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "yes", "r2", 0.8, {}),
        AgentOutput("a3", "no", "r3", 0.7, {})
    ]

    confidence = calculate_consensus_confidence(outputs, "yes")
    # 2/3 agents * avg(0.9, 0.8) = 0.667 * 0.85 = 0.567
    assert 0.55 < confidence < 0.60


def test_extract_majority_decision():
    """Test majority decision extraction."""
    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "yes", "r2", 0.8, {}),
        AgentOutput("a3", "no", "r3", 0.7, {})
    ]

    decision = extract_majority_decision(outputs)
    assert decision == "yes"

    # Test tie
    outputs.append(AgentOutput("a4", "no", "r4", 0.8, {}))
    decision = extract_majority_decision(outputs)
    assert decision is None  # Tie
```

---

## Success Metrics

- [ ] File created: `src/strategies/base.py`
- [ ] All tests pass: `pytest tests/test_strategies/test_base.py -v`
- [ ] Code coverage >90%
- [ ] Can import: `from src.strategies.base import CollaborationStrategy`
- [ ] Type checking passes: `mypy src/strategies/base.py`

---

## Dependencies

**Blocked by:** None (foundation task)

**Blocks:**
- m3-03-consensus-strategy (needs interface)
- m3-04-debate-strategy (needs interface)
- m3-05-merit-weighted-resolution (needs interface)
- m3-07-parallel-stage-execution (needs interface)

---

## Design References

- [Vision Document - Merit-Based Collaboration](../../META_AUTONOMOUS_FRAMEWORK_VISION.md#why-merit-based-collaboration-matters)
- [Technical Specification - Collaboration Configuration](../../TECHNICAL_SPECIFICATION.md)

---

## Notes

**Why This Interface:**
- Enables experimentation with different collaboration patterns
- Decouples strategy logic from execution framework
- Supports plugin architecture (custom strategies)
- Feature detection via `get_capabilities()` for runtime checks

**Design Decisions:**
- `AgentOutput` dataclass standardizes agent results
- `SynthesisResult` includes conflicts for observability
- `detect_conflicts()` helper reduces code duplication
- Utility functions for common operations (consensus, majority)

**Critical:**
- This is the foundation for all M3 collaboration
- Keep interface simple and stable (avoid breaking changes)
- Focus on extensibility (new strategies should be easy to add)
- Observability first (track conflicts, votes, reasoning)

**Future Extensions (M4+):**
- Async synthesis support (`async def asynthesize()`)
- Streaming synthesis (yield intermediate results)
- Multi-round debate state management
- Agent merit score integration
