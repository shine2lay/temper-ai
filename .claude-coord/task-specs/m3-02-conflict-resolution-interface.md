# Task: m3-02-conflict-resolution-interface - Create Conflict Resolution Interface

**Priority:** CRITICAL (P1)
**Effort:** 5 hours
**Status:** in_progress
**Owner:** agent-7ffeca

---

## Summary

Create abstract base class for conflict resolution strategies that define how to resolve disagreements when agents reach different conclusions. While `CollaborationStrategy` detects conflicts, `ConflictResolutionStrategy` provides mechanisms to resolve them through tiebreaking, escalation, negotiation, or fallback approaches.

---

## Files to Create

- `src/strategies/conflict_resolution.py` - ConflictResolutionStrategy ABC and implementations (~250 lines)
- `tests/test_strategies/test_conflict_resolution.py` - Resolution strategy tests

---

## Files to Modify

- `src/strategies/__init__.py` - Export conflict resolution classes

---

## Acceptance Criteria

### Core Functionality
- [x] `ConflictResolutionStrategy` ABC with `resolve(conflict, agent_outputs, config) -> ResolutionResult` method
- [x] `ResolutionResult` dataclass with decision, method, reasoning, success fields
- [x] `ResolutionMethod` enum defining resolution approaches (tiebreaker, escalation, negotiation, etc.)
- [x] - [ ] `get_capabilities() -> Dict[str, bool]` method for feature detection
- [x] - [ ] Support for multiple resolution rounds (iterative resolution)
- [x] - [ ] Extensible design for custom resolution strategies

### Built-in Implementations
- [x] - [ ] `HighestConfidenceResolver` - Pick agent with highest confidence
- [x] - [ ] `MeritWeightedResolver` - Weight by agent merit scores (stub for M4)
- [x] - [ ] `RandomTiebreakerResolver` - Random selection when tied

### Type Safety
- [x] - [ ] Full type hints for all parameters and return types
- [x] - [ ] Pydantic models or dataclasses for all data structures
- [x] - [ ] Runtime validation of inputs

### Documentation
- [x] - [ ] Complete docstrings with examples for all classes and methods
- [x] - [ ] Usage examples in module docstring
- [x] - [ ] Design rationale documented

### Testing
- [x] - [ ] Test ConflictResolutionStrategy cannot be instantiated directly
- [x] - [x] - [ ] Test ResolutionResult dataclass construction
- [x] - [ ] Test each built-in resolver implementation
- [x] - [ ] Test resolution failure handling
- [x] - [ ] Test integration with Conflict dataclass from base.py

---

## Implementation Details

### Class Structure

```python
"""Conflict resolution strategies for multi-agent disagreements.

This module defines interfaces and implementations for resolving conflicts
when agents reach different conclusions. While CollaborationStrategy detects
conflicts, ConflictResolutionStrategy provides mechanisms to resolve them.

Resolution Methods:
- Tiebreaker: Select winning agent/decision based on rules
- Escalation: Escalate to human or higher authority
- Negotiation: Multi-round debate to reach consensus
- Fallback: Use default/safe decision

Example:
    >>> from src.strategies.base import Conflict, AgentOutput
    >>> conflict = Conflict(
    ...     agents=["a1", "a2"],
    ...     decisions=["yes", "no"],
    ...     disagreement_score=1.0,
    ...     context={}
    ... )
    >>> outputs = [
    ...     AgentOutput("a1", "yes", "reason1", 0.9, {}),
    ...     AgentOutput("a2", "no", "reason2", 0.8, {})
    ... ]
    >>> resolver = HighestConfidenceResolver()
    >>> result = resolver.resolve(conflict, outputs, {})
    >>> result.decision
    'yes'  # a1 has higher confidence
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import random

from src.strategies.base import Conflict, AgentOutput


class ResolutionMethod(Enum):
    """Methods for resolving conflicts.

    Attributes:
        HIGHEST_CONFIDENCE: Pick agent with highest confidence
        MERIT_WEIGHTED: Weight by agent merit scores
        RANDOM_TIEBREAKER: Random selection
        ESCALATION: Escalate to human/authority
        NEGOTIATION: Multi-round debate
        FALLBACK: Use safe default
        MAJORITY_PLUS_CONFIDENCE: Combine majority + confidence
    """
    HIGHEST_CONFIDENCE = "highest_confidence"
    MERIT_WEIGHTED = "merit_weighted"
    RANDOM_TIEBREAKER = "random_tiebreaker"
    ESCALATION = "escalation"
    NEGOTIATION = "negotiation"
    FALLBACK = "fallback"
    MAJORITY_PLUS_CONFIDENCE = "majority_plus_confidence"


@dataclass
class ResolutionResult:
    """Result of conflict resolution.

    Attributes:
        decision: Resolved decision (from one of the conflicting options)
        method: Resolution method used
        reasoning: Explanation of how conflict was resolved
        success: Whether resolution succeeded
        confidence: Confidence in resolution (0-1)
        metadata: Additional info (rounds, tiebreaker_used, escalated, etc.)

    Example:
        >>> result = ResolutionResult(
        ...     decision="Option A",
        ...     method="highest_confidence",
        ...     reasoning="Agent1 had highest confidence (0.95)",
        ...     success=True,
        ...     confidence=0.95,
        ...     metadata={"winner": "Agent1", "tiebreaker_used": False}
        ... )
    """
    decision: Any
    method: str
    reasoning: str
    success: bool  # True if resolved, False if needs escalation
    confidence: float  # Confidence in resolution
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate confidence is in valid range."""
        if not 0 <= self.confidence <= 1:
            raise ValueError(
                f"Confidence must be between 0 and 1, got {self.confidence}"
            )


class ConflictResolutionStrategy(ABC):
    """Abstract base class for conflict resolution strategies.

    Conflict resolution strategies define how to resolve disagreements
    when agents reach different conclusions. The strategy receives a
    Conflict object (from CollaborationStrategy.detect_conflicts) and
    attempts to resolve it.

    Subclasses must implement:
    - resolve(): Core resolution logic
    - get_capabilities(): Feature detection

    Example:
        >>> class MyResolver(ConflictResolutionStrategy):
        ...     def resolve(self, conflict, agent_outputs, config):
        ...         # Custom resolution logic
        ...         return ResolutionResult(...)
        ...     def get_capabilities(self):
        ...         return {"supports_negotiation": False}
        >>>
        >>> resolver = MyResolver()
        >>> result = resolver.resolve(conflict, outputs, {})
        >>> if result.success:
        ...     print(f"Resolved to: {result.decision}")
    """

    @abstractmethod
    def resolve(
        self,
        conflict: Conflict,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> ResolutionResult:
        """Resolve a conflict between agents.

        Args:
            conflict: Conflict to resolve (from detect_conflicts)
            agent_outputs: All agent outputs (for context)
            config: Strategy-specific configuration

        Returns:
            ResolutionResult with decision, method, reasoning, success

        Raises:
            ValueError: If conflict or agent_outputs invalid
            RuntimeError: If resolution completely fails

        Example:
            >>> conflict = Conflict(["a1", "a2"], ["yes", "no"], 1.0, {})
            >>> outputs = [
            ...     AgentOutput("a1", "yes", "r1", 0.9, {}),
            ...     AgentOutput("a2", "no", "r2", 0.8, {})
            ... ]
            >>> result = resolver.resolve(conflict, outputs, {})
            >>> result.decision
            'yes'
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, bool]:
        """Get resolver capabilities.

        Returns:
            Dict of capability flags:
            - supports_negotiation: Multi-round negotiation
            - supports_escalation: Can escalate to human
            - supports_merit_weighting: Uses agent merit scores
            - supports_iterative: Can resolve iteratively
            - deterministic: Same inputs always produce same output
        """
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """Get resolver metadata.

        Returns:
            Resolver metadata:
            - name: Resolver class name
            - version: Resolver version
            - description: Brief description
            - config_schema: Expected config format
        """
        return {
            "name": self.__class__.__name__,
            "version": "1.0",
            "description": self.__doc__ or "",
            "config_schema": {}
        }

    def validate_inputs(
        self,
        conflict: Conflict,
        agent_outputs: List[AgentOutput]
    ) -> None:
        """Validate inputs before resolution.

        Args:
            conflict: Conflict to validate
            agent_outputs: Outputs to validate

        Raises:
            ValueError: If validation fails
        """
        if not isinstance(conflict, Conflict):
            raise ValueError("conflict must be a Conflict instance")

        if not agent_outputs:
            raise ValueError("agent_outputs cannot be empty")

        if not all(isinstance(o, AgentOutput) for o in agent_outputs):
            raise ValueError("All outputs must be AgentOutput instances")

        # Verify conflict agents exist in outputs
        output_agents = {o.agent_name for o in agent_outputs}
        conflict_agents = set(conflict.agents)

        if not conflict_agents.issubset(output_agents):
            missing = conflict_agents - output_agents
            raise ValueError(
                f"Conflict references agents not in outputs: {missing}"
            )


# Built-in Implementations

class HighestConfidenceResolver(ConflictResolutionStrategy):
    """Resolve conflicts by selecting agent with highest confidence.

    This resolver picks the decision from the agent with the highest
    confidence score. Simple and effective for most cases.

    Example:
        >>> outputs = [
        ...     AgentOutput("a1", "yes", "r1", 0.9, {}),
        ...     AgentOutput("a2", "no", "r2", 0.8, {})
        ... ]
        >>> resolver = HighestConfidenceResolver()
        >>> conflict = Conflict(["a1", "a2"], ["yes", "no"], 1.0, {})
        >>> result = resolver.resolve(conflict, outputs, {})
        >>> result.decision
        'yes'  # a1 has confidence 0.9 > 0.8
    """

    def resolve(
        self,
        conflict: Conflict,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> ResolutionResult:
        """Resolve by selecting highest confidence agent."""
        self.validate_inputs(conflict, agent_outputs)

        # Filter to conflicting agents
        conflicting_outputs = [
            o for o in agent_outputs if o.agent_name in conflict.agents
        ]

        # Find highest confidence
        winner = max(conflicting_outputs, key=lambda o: o.confidence)

        return ResolutionResult(
            decision=winner.decision,
            method=ResolutionMethod.HIGHEST_CONFIDENCE.value,
            reasoning=(
                f"Selected {winner.agent_name} with highest confidence "
                f"({winner.confidence:.2f})"
            ),
            success=True,
            confidence=winner.confidence,
            metadata={
                "winner": winner.agent_name,
                "all_confidences": {
                    o.agent_name: o.confidence for o in conflicting_outputs
                }
            }
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Capabilities of highest confidence resolver."""
        return {
            "supports_negotiation": False,
            "supports_escalation": False,
            "supports_merit_weighting": False,
            "supports_iterative": False,
            "deterministic": True
        }


class RandomTiebreakerResolver(ConflictResolutionStrategy):
    """Resolve conflicts by random selection.

    This resolver randomly selects one of the conflicting decisions.
    Useful as a last resort or for A/B testing different strategies.

    Example:
        >>> resolver = RandomTiebreakerResolver(seed=42)
        >>> result = resolver.resolve(conflict, outputs, {})
        >>> result.success
        True
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialize with optional random seed for determinism.

        Args:
            seed: Random seed for reproducibility (None for non-deterministic)
        """
        self.seed = seed
        self.rng = random.Random(seed)

    def resolve(
        self,
        conflict: Conflict,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> ResolutionResult:
        """Resolve by random selection."""
        self.validate_inputs(conflict, agent_outputs)

        # Filter to conflicting agents
        conflicting_outputs = [
            o for o in agent_outputs if o.agent_name in conflict.agents
        ]

        # Random selection
        winner = self.rng.choice(conflicting_outputs)

        # Average confidence as resolution confidence
        avg_confidence = sum(o.confidence for o in conflicting_outputs) / len(conflicting_outputs)

        return ResolutionResult(
            decision=winner.decision,
            method=ResolutionMethod.RANDOM_TIEBREAKER.value,
            reasoning=f"Randomly selected {winner.agent_name}",
            success=True,
            confidence=avg_confidence,
            metadata={
                "winner": winner.agent_name,
                "seed": self.seed,
                "candidates": [o.agent_name for o in conflicting_outputs]
            }
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Capabilities of random tiebreaker."""
        return {
            "supports_negotiation": False,
            "supports_escalation": False,
            "supports_merit_weighting": False,
            "supports_iterative": False,
            "deterministic": self.seed is not None
        }


class MeritWeightedResolver(ConflictResolutionStrategy):
    """Resolve conflicts by weighting agents by merit scores.

    This resolver uses agent merit scores (from metadata) to weight
    decisions. Agents with higher merit have more influence.

    NOTE: Full merit tracking is in M4. This is a stub implementation
    that uses confidence as a proxy for merit.

    Example:
        >>> outputs = [
        ...     AgentOutput("expert", "yes", "r1", 0.8, {"merit": 0.95}),
        ...     AgentOutput("novice", "no", "r2", 0.9, {"merit": 0.6})
        ... ]
        >>> resolver = MeritWeightedResolver()
        >>> result = resolver.resolve(conflict, outputs, {})
        >>> result.decision
        'yes'  # expert has higher merit
    """

    def resolve(
        self,
        conflict: Conflict,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> ResolutionResult:
        """Resolve by merit-weighted voting."""
        self.validate_inputs(conflict, agent_outputs)

        # Filter to conflicting agents
        conflicting_outputs = [
            o for o in agent_outputs if o.agent_name in conflict.agents
        ]

        # Get merit scores (use confidence as proxy if not provided)
        merit_scores = {}
        for output in conflicting_outputs:
            merit = output.metadata.get("merit", output.confidence)
            merit_scores[output.agent_name] = merit

        # Find highest merit
        winner = max(conflicting_outputs, key=lambda o: merit_scores[o.agent_name])
        winner_merit = merit_scores[winner.agent_name]

        return ResolutionResult(
            decision=winner.decision,
            method=ResolutionMethod.MERIT_WEIGHTED.value,
            reasoning=(
                f"Selected {winner.agent_name} with highest merit "
                f"({winner_merit:.2f})"
            ),
            success=True,
            confidence=winner_merit,
            metadata={
                "winner": winner.agent_name,
                "merit_scores": merit_scores,
                "note": "Using confidence as merit proxy (full merit in M4)"
            }
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Capabilities of merit-weighted resolver."""
        return {
            "supports_negotiation": False,
            "supports_escalation": False,
            "supports_merit_weighting": True,
            "supports_iterative": False,
            "deterministic": True
        }


# Utility functions

def create_resolver(
    method: ResolutionMethod,
    config: Optional[Dict[str, Any]] = None
) -> ConflictResolutionStrategy:
    """Factory function to create resolver by method.

    Args:
        method: Resolution method enum
        config: Method-specific configuration

    Returns:
        ConflictResolutionStrategy instance

    Raises:
        ValueError: If method not supported

    Example:
        >>> resolver = create_resolver(ResolutionMethod.HIGHEST_CONFIDENCE)
        >>> isinstance(resolver, HighestConfidenceResolver)
        True
    """
    config = config or {}

    if method == ResolutionMethod.HIGHEST_CONFIDENCE:
        return HighestConfidenceResolver()
    elif method == ResolutionMethod.RANDOM_TIEBREAKER:
        seed = config.get("seed")
        return RandomTiebreakerResolver(seed=seed)
    elif method == ResolutionMethod.MERIT_WEIGHTED:
        return MeritWeightedResolver()
    else:
        raise ValueError(f"Unsupported resolution method: {method}")
```

---

## Test Strategy

### Unit Tests (`tests/test_strategies/test_conflict_resolution.py`)

```python
import pytest
from src.strategies.base import Conflict, AgentOutput
from src.strategies.conflict_resolution import (
    ConflictResolutionStrategy,
    ResolutionResult,
    ResolutionMethod,
    HighestConfidenceResolver,
    RandomTiebreakerResolver,
    MeritWeightedResolver,
    create_resolver
)


def test_resolution_strategy_is_abstract():
    """ConflictResolutionStrategy cannot be instantiated."""
    with pytest.raises(TypeError):
        ConflictResolutionStrategy()


def test_resolution_result_validation():
    """Test ResolutionResult validation."""
    result = ResolutionResult(
        decision="yes",
        method="test",
        reasoning="test",
        success=True,
        confidence=0.9,
        metadata={}
    )
    assert result.confidence == 0.9

    # Invalid confidence
    with pytest.raises(ValueError, match="Confidence must be"):
        ResolutionResult("yes", "test", "test", True, 1.5, {})


def test_highest_confidence_resolver():
    """Test highest confidence resolution."""
    resolver = HighestConfidenceResolver()

    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "no", "r2", 0.7, {}),
        AgentOutput("a3", "yes", "r3", 0.8, {})
    ]

    conflict = Conflict(
        agents=["a1", "a2"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result = resolver.resolve(conflict, outputs, {})

    assert result.success
    assert result.decision == "yes"  # a1 has highest confidence
    assert result.confidence == 0.9
    assert result.metadata["winner"] == "a1"


def test_random_tiebreaker_deterministic():
    """Test random tiebreaker with seed is deterministic."""
    resolver1 = RandomTiebreakerResolver(seed=42)
    resolver2 = RandomTiebreakerResolver(seed=42)

    outputs = [
        AgentOutput("a1", "yes", "r1", 0.9, {}),
        AgentOutput("a2", "no", "r2", 0.8, {})
    ]

    conflict = Conflict(
        agents=["a1", "a2"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result1 = resolver1.resolve(conflict, outputs, {})
    result2 = resolver2.resolve(conflict, outputs, {})

    # Same seed should produce same result
    assert result1.decision == result2.decision


def test_merit_weighted_resolver():
    """Test merit-weighted resolution."""
    resolver = MeritWeightedResolver()

    outputs = [
        AgentOutput("expert", "yes", "r1", 0.8, {"merit": 0.95}),
        AgentOutput("novice", "no", "r2", 0.9, {"merit": 0.6})
    ]

    conflict = Conflict(
        agents=["expert", "novice"],
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    result = resolver.resolve(conflict, outputs, {})

    assert result.success
    assert result.decision == "yes"  # expert has higher merit
    assert result.metadata["winner"] == "expert"


def test_resolver_factory():
    """Test resolver factory function."""
    # Highest confidence
    resolver = create_resolver(ResolutionMethod.HIGHEST_CONFIDENCE)
    assert isinstance(resolver, HighestConfidenceResolver)

    # Random with seed
    resolver = create_resolver(
        ResolutionMethod.RANDOM_TIEBREAKER,
        {"seed": 42}
    )
    assert isinstance(resolver, RandomTiebreakerResolver)

    # Merit weighted
    resolver = create_resolver(ResolutionMethod.MERIT_WEIGHTED)
    assert isinstance(resolver, MeritWeightedResolver)


def test_validate_inputs_missing_agents():
    """Test validation catches agents not in outputs."""
    resolver = HighestConfidenceResolver()

    outputs = [AgentOutput("a1", "yes", "r1", 0.9, {})]

    conflict = Conflict(
        agents=["a1", "a2"],  # a2 not in outputs
        decisions=["yes", "no"],
        disagreement_score=1.0,
        context={}
    )

    with pytest.raises(ValueError, match="not in outputs"):
        resolver.resolve(conflict, outputs, {})
```

---

## Success Metrics

- [x] File created: `src/strategies/conflict_resolution.py`
- [x] - [ ] All tests pass: `pytest tests/test_strategies/test_conflict_resolution.py -v`
- [x] - [ ] Code coverage >90%
- [x] - [ ] Can import: `from src.strategies.conflict_resolution import ConflictResolutionStrategy`
- [x] - [ ] Type checking passes: `mypy src/strategies/conflict_resolution.py --strict`
- [x] - [ ] Integration: Works with Conflict dataclass from base.py

---

## Dependencies

**Blocked by:**
- m3-01-collaboration-strategy-interface (needs Conflict, AgentOutput types) ✅ COMPLETED

**Blocks:**
- m3-05-merit-weighted-resolution (needs ConflictResolutionStrategy interface)
- m3-06-strategy-registry (needs both interfaces for registration)

---

## Design References

- [Existing base.py](../../src/strategies/base.py) - Conflict and AgentOutput dataclasses
- [M3-01 Task Spec](./m3-01-collaboration-strategy-interface.md) - Collaboration interface design

---

## Notes

**Why Separate Interface:**
- `CollaborationStrategy` focuses on synthesis (combining outputs)
- `ConflictResolutionStrategy` focuses on resolution (breaking ties/conflicts)
- Separation of concerns: detection vs resolution
- Enables mixing and matching (e.g., consensus + highest-confidence resolver)

**Design Decisions:**
- `ResolutionResult.success` flag enables escalation paths
- Built-in resolvers cover common cases (confidence, merit, random)
- Factory function simplifies resolver creation
- Extensible for custom resolvers (debate, negotiation) in later milestones

**Critical:**
- Keep interface stable (this is foundation for M3 conflict handling)
- Validate inputs thoroughly (conflict agents must exist in outputs)
- Support deterministic and non-deterministic resolvers
- `MeritWeightedResolver` is stub using confidence proxy (full merit in M4)

**Future Extensions (M4+):**
- Negotiation resolver (multi-round debate)
- Escalation resolver (human-in-the-loop)
- Composite resolver (chain multiple strategies)
- Async resolution support
