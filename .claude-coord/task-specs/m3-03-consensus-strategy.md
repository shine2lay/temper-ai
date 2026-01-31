# Task: m3-03-consensus-strategy - Implement Consensus Strategy

**Priority:** CRITICAL (P0)
**Effort:** 8 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement ConsensusStrategy as the reference implementation for collaboration strategies. Uses majority voting (>50% agreement) with tie-breaking based on highest confidence. Simplest strategy that all others can reference.

---

## Files to Create

- `src/strategies/consensus.py` - ConsensusStrategy implementation (~250 lines)
- `tests/test_strategies/test_consensus.py` - Strategy tests

---

## Acceptance Criteria

### Core Functionality
- [ ] Implements `CollaborationStrategy` interface
- [ ] Majority voting (>50% agreement) for decision
- [ ] Tie-breaking: highest confidence wins
- [ ] Handles no-majority scenario (escalates to conflict resolver)
- [ ] Tracks vote counts and participation
- [ ] Detects conflicts automatically

### Synthesis Quality
- [ ] Calculates confidence based on consensus strength + average supporter confidence
- [ ] Provides detailed reasoning in SynthesisResult
- [ ] Tracks all votes in metadata
- [ ] Identifies winning and losing agents

### Feature Support
- [ ] `get_capabilities()` returns accurate feature flags
- [ ] No debate support (single-round voting)
- [ ] No convergence detection (not multi-round)
- [ ] Supports partial participation (min_agents check)

### Testing
- [ ] Test unanimous decision (all agents agree)
- [ ] Test majority decision (2/3 agents agree)
- [ ] Test tie scenario (50/50 split)
- [ ] Test no majority (3-way split)
- [ ] Test single agent edge case
- [ ] Integration test with mock agents
- [ ] Coverage >90%

---

## Implementation Details

### Class Implementation

```python
"""Consensus-based collaboration strategy.

This strategy implements simple majority voting:
- Count votes for each decision option
- Decision with >50% support wins
- Tie-breaking: highest average confidence
- No majority: escalate to conflict resolution
"""
from typing import Dict, Any, List
from collections import Counter

from src.strategies.base import (
    CollaborationStrategy,
    AgentOutput,
    SynthesisResult,
    Conflict,
    calculate_consensus_confidence
)


class ConsensusStrategy(CollaborationStrategy):
    """Simple majority-voting collaboration strategy.

    Agents vote on decisions, and the option with >50% support wins.
    Confidence is calculated based on:
    - Consensus strength (% of agents agreeing)
    - Average confidence of supporting agents

    Example:
        >>> strategy = ConsensusStrategy()
        >>> outputs = [
        ...     AgentOutput("a1", "Option A", "because...", 0.9, {}),
        ...     AgentOutput("a2", "Option A", "I agree...", 0.8, {}),
        ...     AgentOutput("a3", "Option B", "but...", 0.7, {})
        ... ]
        >>> result = strategy.synthesize(outputs, {})
        >>> result.decision
        'Option A'
        >>> result.confidence
        # (2/3 agents) * avg(0.9, 0.8) = 0.667 * 0.85 = 0.567
    """

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize using majority voting.

        Args:
            agent_outputs: Outputs from all agents
            config: Strategy configuration (optional):
                - min_agents: Minimum agents required (default: 1)
                - min_consensus: Minimum consensus % (default: 0.51)
                - tie_breaker: "confidence" | "first" (default: "confidence")

        Returns:
            SynthesisResult with majority decision

        Raises:
            ValueError: If agent_outputs is invalid
        """
        # Validate inputs
        self.validate_inputs(agent_outputs)

        # Get config
        min_agents = config.get("min_agents", 1)
        min_consensus = config.get("min_consensus", 0.51)  # >50%
        tie_breaker = config.get("tie_breaker", "confidence")

        # Check minimum agents
        if len(agent_outputs) < min_agents:
            raise ValueError(
                f"Need at least {min_agents} agents, got {len(agent_outputs)}"
            )

        # Count votes
        vote_counts = Counter(str(o.decision) for o in agent_outputs)
        total_votes = len(agent_outputs)

        # Get majority decision
        most_common = vote_counts.most_common()

        if not most_common:
            raise RuntimeError("No votes found")

        # Check for tie (multiple decisions with same count)
        max_count = most_common[0][1]
        tied_decisions = [d for d, count in most_common if count == max_count]

        if len(tied_decisions) > 1:
            # Tie detected - use tie-breaking
            decision = self._break_tie(tied_decisions, agent_outputs, tie_breaker)
        else:
            decision = most_common[0][0]

        # Check if we have majority (>50%)
        decision_support = vote_counts[decision] / total_votes

        if decision_support < min_consensus:
            # No clear majority - create conflict
            conflicts = self.detect_conflicts(agent_outputs, threshold=0.3)
            return SynthesisResult(
                decision=decision,  # Best effort decision
                confidence=decision_support * 0.7,  # Reduced confidence
                method="consensus_weak",
                votes=dict(vote_counts),
                conflicts=conflicts,
                reasoning=(
                    f"No clear majority. Decision '{decision}' had {decision_support:.1%} "
                    f"support, below {min_consensus:.1%} threshold. "
                    f"Consider conflict resolution."
                ),
                metadata={
                    "total_agents": total_votes,
                    "decision_support": decision_support,
                    "min_consensus": min_consensus,
                    "needs_conflict_resolution": True
                }
            )

        # Calculate confidence
        confidence = calculate_consensus_confidence(agent_outputs, decision)

        # Get supporting and dissenting agents
        supporters = [o.agent_name for o in agent_outputs if str(o.decision) == decision]
        dissenters = [o.agent_name for o in agent_outputs if str(o.decision) != decision]

        # Detect conflicts
        conflicts = self.detect_conflicts(agent_outputs, threshold=0.3)

        # Build reasoning
        reasoning = self._build_reasoning(
            decision, decision_support, supporters, dissenters, vote_counts
        )

        return SynthesisResult(
            decision=decision,
            confidence=confidence,
            method="consensus",
            votes=dict(vote_counts),
            conflicts=conflicts,
            reasoning=reasoning,
            metadata={
                "total_agents": total_votes,
                "supporters": supporters,
                "dissenters": dissenters,
                "decision_support": decision_support,
                "avg_supporter_confidence": sum(
                    o.confidence for o in agent_outputs if str(o.decision) == decision
                ) / len(supporters)
            }
        )

    def _break_tie(
        self,
        tied_decisions: List[str],
        agent_outputs: List[AgentOutput],
        method: str = "confidence"
    ) -> str:
        """Break tie between decisions with equal votes.

        Args:
            tied_decisions: List of decisions that are tied
            agent_outputs: All agent outputs
            method: Tie-breaking method ("confidence" or "first")

        Returns:
            Winning decision
        """
        if method == "first":
            # Return first decision in vote order
            return tied_decisions[0]

        # Confidence-based: highest average confidence wins
        decision_confidences = {}
        for decision in tied_decisions:
            supporters = [
                o for o in agent_outputs
                if str(o.decision) == decision
            ]
            avg_confidence = sum(o.confidence for o in supporters) / len(supporters)
            decision_confidences[decision] = avg_confidence

        # Return decision with highest confidence
        return max(decision_confidences.items(), key=lambda x: x[1])[0]

    def _build_reasoning(
        self,
        decision: str,
        support_pct: float,
        supporters: List[str],
        dissenters: List[str],
        vote_counts: Dict[str, int]
    ) -> str:
        """Build human-readable reasoning for decision.

        Args:
            decision: Final decision
            support_pct: Percentage of agents supporting decision
            supporters: List of supporting agent names
            dissenters: List of dissenting agent names
            vote_counts: Vote count breakdown

        Returns:
            Reasoning string
        """
        lines = []
        lines.append(
            f"Consensus reached: '{decision}' with {support_pct:.1%} support "
            f"({len(supporters)}/{len(supporters) + len(dissenters)} agents)."
        )

        # Vote breakdown
        if len(vote_counts) > 1:
            vote_breakdown = ", ".join(
                f"'{option}': {count}" for option, count in vote_counts.items()
            )
            lines.append(f"Vote breakdown: {vote_breakdown}.")

        # Supporters
        if supporters:
            lines.append(f"Supporting agents: {', '.join(supporters)}.")

        # Dissenters
        if dissenters:
            lines.append(f"Dissenting agents: {', '.join(dissenters)}.")

        return " ".join(lines)

    def get_capabilities(self) -> Dict[str, bool]:
        """Get strategy capabilities."""
        return {
            "supports_debate": False,  # Single-round voting only
            "supports_convergence": False,  # No multi-round
            "supports_merit_weighting": False,  # Equal weight per agent
            "supports_partial_participation": True,  # Can handle missing agents
            "supports_async": False,  # Sync only for now
            "deterministic": True,  # Same input -> same output
            "requires_conflict_resolver": True  # Needs resolver for ties
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Get strategy metadata."""
        return {
            **super().get_metadata(),
            "config_schema": {
                "min_agents": {
                    "type": "int",
                    "default": 1,
                    "description": "Minimum agents required"
                },
                "min_consensus": {
                    "type": "float",
                    "default": 0.51,
                    "description": "Minimum consensus percentage (0-1)"
                },
                "tie_breaker": {
                    "type": "str",
                    "default": "confidence",
                    "options": ["confidence", "first"],
                    "description": "Tie-breaking method"
                }
            }
        }
```

---

## Test Strategy

### Unit Tests (`tests/test_strategies/test_consensus.py`)

```python
import pytest
from src.strategies.consensus import ConsensusStrategy
from src.strategies.base import AgentOutput, SynthesisResult


def test_unanimous_consensus():
    """Test unanimous decision (all agents agree)."""
    strategy = ConsensusStrategy()
    outputs = [
        AgentOutput("a1", "Option A", "reason1", 0.9, {}),
        AgentOutput("a2", "Option A", "reason2", 0.8, {}),
        AgentOutput("a3", "Option A", "reason3", 0.85, {})
    ]

    result = strategy.synthesize(outputs, {})

    assert result.decision == "Option A"
    assert result.confidence > 0.8
    assert result.method == "consensus"
    assert result.votes["Option A"] == 3
    assert len(result.conflicts) == 0
    assert "100.0% support" in result.reasoning


def test_majority_consensus():
    """Test majority decision (2/3 agents agree)."""
    strategy = ConsensusStrategy()
    outputs = [
        AgentOutput("a1", "Option A", "reason1", 0.9, {}),
        AgentOutput("a2", "Option A", "reason2", 0.8, {}),
        AgentOutput("a3", "Option B", "reason3", 0.7, {})
    ]

    result = strategy.synthesize(outputs, {})

    assert result.decision == "Option A"
    # Confidence: (2/3) * avg(0.9, 0.8) = 0.667 * 0.85 = 0.567
    assert 0.55 < result.confidence < 0.60
    assert result.votes == {"Option A": 2, "Option B": 1}
    assert len(result.conflicts) == 1  # Disagreement detected


def test_tie_breaking_by_confidence():
    """Test tie-breaking using confidence."""
    strategy = ConsensusStrategy()
    outputs = [
        AgentOutput("a1", "Option A", "reason1", 0.9, {}),
        AgentOutput("a2", "Option B", "reason2", 0.7, {})
    ]

    result = strategy.synthesize(outputs, {"tie_breaker": "confidence"})

    # Option A has higher confidence (0.9 vs 0.7)
    assert result.decision == "Option A"


def test_no_majority_creates_conflict():
    """Test 3-way split with no majority."""
    strategy = ConsensusStrategy()
    outputs = [
        AgentOutput("a1", "Option A", "reason1", 0.8, {}),
        AgentOutput("a2", "Option B", "reason2", 0.8, {}),
        AgentOutput("a3", "Option C", "reason3", 0.8, {})
    ]

    result = strategy.synthesize(outputs, {})

    # Should still return a decision but with low confidence
    assert result.decision in ["Option A", "Option B", "Option C"]
    assert result.confidence < 0.5  # Low confidence
    assert result.metadata["needs_conflict_resolution"] is True


def test_min_consensus_threshold():
    """Test custom minimum consensus threshold."""
    strategy = ConsensusStrategy()
    outputs = [
        AgentOutput("a1", "Option A", "reason1", 0.9, {}),
        AgentOutput("a2", "Option A", "reason2", 0.8, {}),
        AgentOutput("a3", "Option B", "reason3", 0.7, {}),
        AgentOutput("a4", "Option C", "reason4", 0.7, {})
    ]

    # 2/4 = 50% support, below 75% threshold
    result = strategy.synthesize(outputs, {"min_consensus": 0.75})

    assert result.metadata["needs_conflict_resolution"] is True
    assert result.metadata["decision_support"] == 0.5


def test_single_agent():
    """Test edge case with single agent."""
    strategy = ConsensusStrategy()
    outputs = [AgentOutput("a1", "Option A", "reason", 0.9, {})]

    result = strategy.synthesize(outputs, {})

    assert result.decision == "Option A"
    assert result.confidence == 0.9  # 100% support * 0.9 confidence


def test_empty_outputs_raises():
    """Test that empty outputs raises ValueError."""
    strategy = ConsensusStrategy()

    with pytest.raises(ValueError, match="cannot be empty"):
        strategy.synthesize([], {})


def test_min_agents_enforcement():
    """Test minimum agents requirement."""
    strategy = ConsensusStrategy()
    outputs = [AgentOutput("a1", "Option A", "reason", 0.9, {})]

    with pytest.raises(ValueError, match="Need at least 2 agents"):
        strategy.synthesize(outputs, {"min_agents": 2})


def test_capabilities():
    """Test strategy capabilities reporting."""
    strategy = ConsensusStrategy()
    caps = strategy.get_capabilities()

    assert caps["supports_debate"] is False
    assert caps["supports_convergence"] is False
    assert caps["supports_partial_participation"] is True
    assert caps["deterministic"] is True


def test_metadata():
    """Test strategy metadata."""
    strategy = ConsensusStrategy()
    metadata = strategy.get_metadata()

    assert metadata["name"] == "ConsensusStrategy"
    assert "min_agents" in metadata["config_schema"]
    assert "min_consensus" in metadata["config_schema"]
```

---

## Success Metrics

- [ ] File created: `src/strategies/consensus.py`
- [ ] All tests pass: `pytest tests/test_strategies/test_consensus.py -v`
- [ ] Code coverage >90%
- [ ] Can instantiate and use: `ConsensusStrategy().synthesize(...)`
- [ ] Handles all edge cases (tie, no majority, single agent)
- [ ] Performance: <50ms for 10 agents

---

## Dependencies

**Blocked by:**
- m3-01-collaboration-strategy-interface (needs CollaborationStrategy ABC)
- m3-02-conflict-resolution-interface (needs Conflict types)

**Blocks:**
- m3-06-strategy-registry (needs implementation to register)
- m3-07-parallel-stage-execution (needs working strategy)
- m3-09-synthesis-node (needs strategy to call)

---

## Design References

- [Vision Document - Merit-Based Collaboration](../../META_AUTONOMOUS_FRAMEWORK_VISION.md)
- [Technical Specification - Stage Collaboration](../../TECHNICAL_SPECIFICATION.md)
- [m3-01 Collaboration Strategy Interface](./m3-01-collaboration-strategy-interface.md)

---

## Notes

**Why Consensus Strategy First:**
- Simplest collaboration pattern (reference for others)
- No multi-round complexity
- Clear voting semantics (majority wins)
- Establishes testing patterns for other strategies

**Design Decisions:**
- Tie-breaking via confidence (not random)
- Weak consensus flagged for conflict resolution
- Detailed reasoning for observability
- Metadata tracks all participation

**Critical:**
- This is the default strategy (most workflows will use this)
- Performance matters (will be called frequently)
- Clear error messages when synthesis fails
- Extensive testing of edge cases

**Future Enhancements (M4+):**
- Async synthesis support
- Weighted voting by agent role
- Quorum requirements
- Time-based voting windows
