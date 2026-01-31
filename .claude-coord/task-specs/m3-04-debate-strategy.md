# Task: m3-04-debate-strategy - Implement DebateAndSynthesize Strategy

**Priority:** HIGH (P1)
**Effort:** 12 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement multi-round debate collaboration strategy where agents iteratively refine arguments until convergence. Key differentiation feature that enables deeper reasoning and higher quality decisions through structured argumentation.

---

## Files to Create

- `src/strategies/debate.py` - DebateAndSynthesize implementation (~400 lines)
- `tests/test_strategies/test_debate.py` - Strategy tests

---

## Acceptance Criteria

### Core Functionality
- [ ] Implements `CollaborationStrategy` interface
- [ ] Multi-round debate with configurable max_rounds (default: 3)
- [ ] Round-robin debate structure (agents respond sequentially)
- [ ] Each round: agents see previous arguments, refine positions
- [ ] Convergence detection (stop early if agreement reached)
- [ ] Final synthesis extracts consensus from debate history

### Debate Mechanics
- [ ] Track arguments from each agent per round
- [ ] Share all arguments with all agents before next round
- [ ] Detect when new insights stop emerging
- [ ] Allow agents to change positions based on arguments
- [ ] Record debate transcript for observability

### Convergence Detection
- [ ] Compare agent decisions across rounds
- [ ] Calculate convergence score (% agents who haven't changed)
- [ ] Configurable convergence threshold (default: 0.8)
- [ ] Early termination when converged
- [ ] Track rounds_to_convergence metric

### Synthesis Quality
- [ ] Extract final consensus from debate
- [ ] Weight by argument strength + agent confidence
- [ ] Identify key arguments that influenced decisions
- [ ] Provide detailed reasoning citing debate points

### Testing
- [ ] Test single-round debate (no convergence needed)
- [ ] Test multi-round convergence (agents reach agreement)
- [ ] Test max_rounds termination
- [ ] Test agents changing positions mid-debate
- [ ] Test no convergence scenario
- [ ] Integration test with mock LLM agents
- [ ] Coverage >85%

---

## Implementation Details

### Class Implementation

```python
"""Debate-based collaboration strategy.

Agents engage in multi-round structured debate:
1. Initial positions: Each agent states decision + reasoning
2. Debate rounds: Agents see others' arguments, refine positions
3. Convergence check: Stop when no new insights emerge
4. Final synthesis: Extract consensus from debate history

This strategy produces higher-quality decisions than simple voting
by allowing agents to consider counter-arguments and refine reasoning.
"""
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass, field

from src.strategies.base import (
    CollaborationStrategy,
    AgentOutput,
    SynthesisResult,
    Conflict,
    calculate_consensus_confidence
)


@dataclass
class DebateRound:
    """Single round of debate.

    Attributes:
        round_number: Round index (0-based)
        agent_outputs: Outputs from all agents this round
        convergence_score: Agreement level (0-1)
        new_insights: Whether new arguments emerged
    """
    round_number: int
    agent_outputs: List[AgentOutput]
    convergence_score: float
    new_insights: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DebateHistory:
    """Complete debate transcript.

    Attributes:
        rounds: All debate rounds
        total_rounds: Number of rounds executed
        converged: Whether debate converged
        convergence_round: Round where convergence occurred
    """
    rounds: List[DebateRound]
    total_rounds: int
    converged: bool
    convergence_round: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class DebateAndSynthesize(CollaborationStrategy):
    """Multi-round debate collaboration strategy.

    Agents iteratively refine arguments through structured debate.
    Produces higher-quality decisions by allowing:
    - Counter-argument consideration
    - Position refinement based on new information
    - Emergence of consensus through reasoning

    Example:
        >>> strategy = DebateAndSynthesize()
        >>> config = {
        ...     "max_rounds": 3,
        ...     "convergence_threshold": 0.8,
        ...     "debate_structure": "round_robin"
        ... }
        >>> # Round 1: Initial positions
        >>> outputs_r1 = [
        ...     AgentOutput("a1", "Option A", "Because X", 0.8, {}),
        ...     AgentOutput("a2", "Option B", "Because Y", 0.8, {}),
        ...     AgentOutput("a3", "Option A", "Because Z", 0.7, {})
        ... ]
        >>> # After seeing arguments, a2 changes to Option A
        >>> result = strategy.synthesize(outputs_r1, config)
        >>> # Debate converges after 2 rounds
    """

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize through multi-round debate.

        Args:
            agent_outputs: Initial outputs from all agents
            config: Strategy configuration:
                - max_rounds: Maximum debate rounds (default: 3)
                - convergence_threshold: Stop when this % unchanged (default: 0.8)
                - debate_structure: "round_robin" | "simultaneous" (default: round_robin)
                - require_unanimous: Require 100% agreement (default: False)
                - min_rounds: Minimum rounds even if converged (default: 1)

        Returns:
            SynthesisResult with debate-refined consensus

        Raises:
            ValueError: If agent_outputs invalid
        """
        # Validate inputs
        self.validate_inputs(agent_outputs)

        # Get config
        max_rounds = config.get("max_rounds", 3)
        convergence_threshold = config.get("convergence_threshold", 0.8)
        require_unanimous = config.get("require_unanimous", False)
        min_rounds = config.get("min_rounds", 1)

        # Initialize debate history
        debate_history = DebateHistory(
            rounds=[],
            total_rounds=0,
            converged=False,
            convergence_round=-1,
            metadata={}
        )

        # Track previous round's decisions
        previous_decisions = None
        current_outputs = agent_outputs

        # Conduct debate rounds
        for round_num in range(max_rounds):
            # Record this round
            convergence_score = self._calculate_convergence(
                current_outputs, previous_decisions
            )

            debate_round = DebateRound(
                round_number=round_num,
                agent_outputs=current_outputs,
                convergence_score=convergence_score,
                new_insights=self._detect_new_insights(
                    current_outputs, previous_decisions
                ),
                metadata={
                    "decision_distribution": self._get_decision_distribution(current_outputs)
                }
            )

            debate_history.rounds.append(debate_round)
            debate_history.total_rounds += 1

            # Check convergence
            if round_num >= min_rounds - 1:  # After minimum rounds
                if convergence_score >= convergence_threshold:
                    debate_history.converged = True
                    debate_history.convergence_round = round_num
                    break

            # Prepare for next round (if not last)
            if round_num < max_rounds - 1:
                previous_decisions = {o.agent_name: o.decision for o in current_outputs}
                # In real implementation, would re-query agents with debate context
                # For now, we work with the outputs we have
                # TODO: Implement multi-turn agent querying in m3-XX

        # Extract final consensus
        final_outputs = debate_history.rounds[-1].agent_outputs
        decision, confidence = self._extract_consensus(
            final_outputs, debate_history, require_unanimous
        )

        # Detect conflicts
        conflicts = self.detect_conflicts(final_outputs, threshold=0.3)

        # Build reasoning from debate
        reasoning = self._build_debate_reasoning(
            decision, debate_history, conflicts
        )

        # Collect votes from final round
        from collections import Counter
        votes = Counter(str(o.decision) for o in final_outputs)

        return SynthesisResult(
            decision=decision,
            confidence=confidence,
            method="debate_and_synthesize",
            votes=dict(votes),
            conflicts=conflicts,
            reasoning=reasoning,
            metadata={
                "debate_history": self._serialize_debate_history(debate_history),
                "total_rounds": debate_history.total_rounds,
                "converged": debate_history.converged,
                "convergence_round": debate_history.convergence_round,
                "final_convergence_score": debate_history.rounds[-1].convergence_score
            }
        )

    def _calculate_convergence(
        self,
        current_outputs: List[AgentOutput],
        previous_decisions: Dict[str, Any] | None
    ) -> float:
        """Calculate convergence score (% agents unchanged).

        Args:
            current_outputs: Current round outputs
            previous_decisions: Previous round decisions by agent

        Returns:
            Convergence score (0-1)
        """
        if previous_decisions is None:
            return 0.0  # First round, no convergence yet

        unchanged_count = 0
        for output in current_outputs:
            prev_decision = previous_decisions.get(output.agent_name)
            if prev_decision is not None and str(output.decision) == str(prev_decision):
                unchanged_count += 1

        return unchanged_count / len(current_outputs)

    def _detect_new_insights(
        self,
        current_outputs: List[AgentOutput],
        previous_decisions: Dict[str, Any] | None
    ) -> bool:
        """Detect if new insights emerged this round.

        Args:
            current_outputs: Current round outputs
            previous_decisions: Previous round decisions

        Returns:
            True if any agent changed position
        """
        if previous_decisions is None:
            return True  # First round always has insights

        for output in current_outputs:
            prev_decision = previous_decisions.get(output.agent_name)
            if prev_decision is not None and str(output.decision) != str(prev_decision):
                return True  # At least one agent changed

        return False

    def _get_decision_distribution(
        self,
        outputs: List[AgentOutput]
    ) -> Dict[str, int]:
        """Get distribution of decisions."""
        from collections import Counter
        return dict(Counter(str(o.decision) for o in outputs))

    def _extract_consensus(
        self,
        final_outputs: List[AgentOutput],
        debate_history: DebateHistory,
        require_unanimous: bool
    ) -> Tuple[Any, float]:
        """Extract final consensus from debate.

        Args:
            final_outputs: Final round outputs
            debate_history: Complete debate history
            require_unanimous: Whether to require 100% agreement

        Returns:
            Tuple of (decision, confidence)
        """
        from collections import Counter

        # Get most common decision
        decisions = [str(o.decision) for o in final_outputs]
        vote_counts = Counter(decisions)
        decision = vote_counts.most_common(1)[0][0]

        # Calculate confidence based on:
        # 1. Consensus strength (% support)
        # 2. Convergence quality (did debate converge?)
        # 3. Average agent confidence

        consensus_strength = vote_counts[decision] / len(final_outputs)

        if require_unanimous and consensus_strength < 1.0:
            confidence = consensus_strength * 0.5  # Penalize non-unanimous
        else:
            # Boost confidence if debate converged
            convergence_bonus = 0.1 if debate_history.converged else 0.0

            # Average confidence of supporters
            supporters = [o for o in final_outputs if str(o.decision) == decision]
            avg_confidence = sum(o.confidence for o in supporters) / len(supporters)

            confidence = min(
                consensus_strength * avg_confidence + convergence_bonus,
                1.0
            )

        return decision, confidence

    def _build_debate_reasoning(
        self,
        decision: Any,
        debate_history: DebateHistory,
        conflicts: List[Conflict]
    ) -> str:
        """Build detailed reasoning from debate history.

        Args:
            decision: Final decision
            debate_history: Complete debate history
            conflicts: Detected conflicts

        Returns:
            Reasoning string
        """
        lines = []

        # Overall outcome
        lines.append(
            f"Debate concluded after {debate_history.total_rounds} rounds with "
            f"decision: '{decision}'."
        )

        if debate_history.converged:
            lines.append(
                f"Convergence achieved at round {debate_history.convergence_round + 1}."
            )
        else:
            lines.append("Maximum rounds reached without full convergence.")

        # Per-round summary
        for round_data in debate_history.rounds:
            dist = round_data.metadata["decision_distribution"]
            dist_str = ", ".join(f"'{k}': {v}" for k, v in dist.items())
            lines.append(
                f"Round {round_data.round_number + 1}: {dist_str} "
                f"(convergence: {round_data.convergence_score:.1%})."
            )

        # Conflicts
        if conflicts:
            lines.append(
                f"Remaining disagreements: {len(conflicts)} conflict(s) detected."
            )

        return " ".join(lines)

    def _serialize_debate_history(self, history: DebateHistory) -> Dict[str, Any]:
        """Serialize debate history for metadata."""
        return {
            "total_rounds": history.total_rounds,
            "converged": history.converged,
            "convergence_round": history.convergence_round,
            "rounds": [
                {
                    "round_number": r.round_number,
                    "convergence_score": r.convergence_score,
                    "new_insights": r.new_insights,
                    "decision_distribution": r.metadata.get("decision_distribution", {})
                }
                for r in history.rounds
            ]
        }

    def get_capabilities(self) -> Dict[str, bool]:
        """Get strategy capabilities."""
        return {
            "supports_debate": True,  # Multi-round debate
            "supports_convergence": True,  # Convergence detection
            "supports_merit_weighting": False,  # Equal weight (for now)
            "supports_partial_participation": True,  # Can handle missing agents
            "supports_async": False,  # Sync only for now
            "deterministic": False,  # Depends on agent responses
            "requires_conflict_resolver": True  # For non-converged debates
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Get strategy metadata."""
        return {
            **super().get_metadata(),
            "config_schema": {
                "max_rounds": {
                    "type": "int",
                    "default": 3,
                    "description": "Maximum debate rounds"
                },
                "convergence_threshold": {
                    "type": "float",
                    "default": 0.8,
                    "description": "Stop when this % agents unchanged (0-1)"
                },
                "debate_structure": {
                    "type": "str",
                    "default": "round_robin",
                    "options": ["round_robin", "simultaneous"],
                    "description": "How agents take turns"
                },
                "require_unanimous": {
                    "type": "bool",
                    "default": False,
                    "description": "Require 100% agreement"
                },
                "min_rounds": {
                    "type": "int",
                    "default": 1,
                    "description": "Minimum rounds even if converged early"
                }
            }
        }
```

---

## Test Strategy

### Unit Tests (`tests/test_strategies/test_debate.py`)

```python
import pytest
from src.strategies.debate import DebateAndSynthesize, DebateRound, DebateHistory
from src.strategies.base import AgentOutput


def test_single_round_debate():
    """Test debate with unanimous decision (converges immediately)."""
    strategy = DebateAndSynthesize()
    outputs = [
        AgentOutput("a1", "Option A", "reason1", 0.9, {}),
        AgentOutput("a2", "Option A", "reason2", 0.8, {}),
        AgentOutput("a3", "Option A", "reason3", 0.85, {})
    ]

    result = strategy.synthesize(outputs, {"max_rounds": 3})

    assert result.decision == "Option A"
    assert result.metadata["total_rounds"] >= 1
    assert result.metadata["converged"] is True


def test_multi_round_convergence():
    """Test debate converging over multiple rounds."""
    # Note: In real implementation, agents would change positions
    # For now, we test the mechanics with static outputs
    strategy = DebateAndSynthesize()

    # Simulating what would happen if agents converge
    outputs = [
        AgentOutput("a1", "Option A", "reason1", 0.9, {}),
        AgentOutput("a2", "Option A", "reason2", 0.8, {}),
        AgentOutput("a3", "Option B", "reason3", 0.7, {})
    ]

    result = strategy.synthesize(outputs, {
        "max_rounds": 3,
        "convergence_threshold": 0.6  # Lower threshold for test
    })

    assert result.decision in ["Option A", "Option B"]
    assert "total_rounds" in result.metadata


def test_max_rounds_termination():
    """Test debate stops at max_rounds."""
    strategy = DebateAndSynthesize()
    outputs = [
        AgentOutput("a1", "Option A", "reason", 0.8, {}),
        AgentOutput("a2", "Option B", "reason", 0.8, {}),
        AgentOutput("a3", "Option C", "reason", 0.8, {})
    ]

    result = strategy.synthesize(outputs, {"max_rounds": 2})

    assert result.metadata["total_rounds"] == 2
    assert result.metadata["converged"] is False  # Didn't converge


def test_convergence_calculation():
    """Test convergence score calculation."""
    strategy = DebateAndSynthesize()

    # All unchanged
    current = [
        AgentOutput("a1", "A", "r", 0.8, {}),
        AgentOutput("a2", "B", "r", 0.8, {})
    ]
    previous = {"a1": "A", "a2": "B"}

    score = strategy._calculate_convergence(current, previous)
    assert score == 1.0  # 100% unchanged

    # One changed
    current[1] = AgentOutput("a2", "A", "r", 0.8, {})
    score = strategy._calculate_convergence(current, previous)
    assert score == 0.5  # 50% unchanged


def test_new_insights_detection():
    """Test detection of new insights."""
    strategy = DebateAndSynthesize()

    # First round - always has insights
    outputs = [AgentOutput("a1", "A", "r", 0.8, {})]
    assert strategy._detect_new_insights(outputs, None) is True

    # No changes - no new insights
    previous = {"a1": "A"}
    assert strategy._detect_new_insights(outputs, previous) is False

    # Position changed - new insight
    outputs = [AgentOutput("a1", "B", "r", 0.8, {})]
    assert strategy._detect_new_insights(outputs, previous) is True


def test_unanimous_requirement():
    """Test require_unanimous config."""
    strategy = DebateAndSynthesize()
    outputs = [
        AgentOutput("a1", "A", "r", 0.9, {}),
        AgentOutput("a2", "A", "r", 0.8, {}),
        AgentOutput("a3", "B", "r", 0.7, {})  # Dissenter
    ]

    result = strategy.synthesize(outputs, {
        "require_unanimous": True,
        "max_rounds": 1
    })

    # Should have lower confidence due to non-unanimous
    assert result.confidence < 0.7


def test_min_rounds_enforcement():
    """Test minimum rounds enforcement."""
    strategy = DebateAndSynthesize()
    outputs = [
        AgentOutput("a1", "A", "r", 0.9, {}),
        AgentOutput("a2", "A", "r", 0.8, {}),
        AgentOutput("a3", "A", "r", 0.85, {})
    ]

    result = strategy.synthesize(outputs, {
        "min_rounds": 2,
        "convergence_threshold": 0.8
    })

    # Should run at least 2 rounds even though unanimous
    assert result.metadata["total_rounds"] >= 2


def test_capabilities():
    """Test strategy capabilities."""
    strategy = DebateAndSynthesize()
    caps = strategy.get_capabilities()

    assert caps["supports_debate"] is True
    assert caps["supports_convergence"] is True
    assert caps["deterministic"] is False  # Depends on agent responses
```

---

## Success Metrics

- [ ] File created: `src/strategies/debate.py`
- [ ] All tests pass: `pytest tests/test_strategies/test_debate.py -v`
- [ ] Code coverage >85%
- [ ] Convergence detection works correctly
- [ ] Debate history properly tracked
- [ ] Performance: <200ms per round (excluding agent calls)

---

## Dependencies

**Blocked by:**
- m3-01-collaboration-strategy-interface (needs CollaborationStrategy ABC)
- m3-02-conflict-resolution-interface (needs Conflict types)
- m3-03-consensus-strategy (reference implementation)

**Blocks:**
- m3-06-strategy-registry (needs implementation to register)
- m3-11-convergence-detection (debate is main use case)

---

## Design References

- [Vision Document - Debate Collaboration](../../META_AUTONOMOUS_FRAMEWORK_VISION.md)
- [Technical Specification - Debate Configuration](../../TECHNICAL_SPECIFICATION.md)

---

## Notes

**Why Debate Strategy:**
- Key differentiation from other frameworks
- Produces higher-quality decisions through argumentation
- Enables agents to refine reasoning
- Mimics human deliberation processes

**Design Decisions:**
- Multi-round with convergence detection (cost-efficient)
- Detailed debate history for observability and learning
- Configurable thresholds (flexibility)
- Support for unanimous requirement (high-stakes decisions)

**Critical:**
- This is a showcase feature for M3
- Performance matters (multi-round can be expensive)
- Convergence detection prevents runaway costs
- Detailed tracking for debugging and learning

**Future Enhancements (M4+):**
- Multi-turn agent support (agents re-query with debate context)
- Argument strength scoring (weight by persuasiveness)
- Debate summarization (LLM summarizes key points)
- Hierarchical debate (sub-debates for complex decisions)
- Merit-weighted debate (experienced agents have more influence)
