"""Consensus-based collaboration strategy.

This strategy implements simple majority voting:
- Count votes for each decision option
- Decision with >50% support wins
- Tie-breaking: highest average confidence
- No majority: escalate to conflict resolution

Design Philosophy:
- Simplest collaboration pattern (reference implementation)
- Single-round voting (no debate or convergence)
- Equal weight per agent (no merit weighting)
- Deterministic (same input -> same output)
- Observability first (detailed reasoning and metadata)

Example:
    >>> from src.strategies.consensus import ConsensusStrategy
    >>> from src.strategies.base import AgentOutput
    >>>
    >>> strategy = ConsensusStrategy()
    >>> outputs = [
    ...     AgentOutput("agent1", "Option A", "reasoning...", 0.9, {}),
    ...     AgentOutput("agent2", "Option A", "I agree...", 0.8, {}),
    ...     AgentOutput("agent3", "Option B", "but...", 0.7, {})
    ... ]
    >>> result = strategy.synthesize(outputs, {})
    >>> result.decision
    'Option A'
    >>> result.confidence  # (2/3) * avg(0.9, 0.8) = 0.567
    0.567
"""

from typing import Any, Dict, List

from src.constants.probabilities import PROB_LOW_MEDIUM, PROB_MEDIUM
from src.constants.limits import PERCENT_50
from src.strategies.base import (
    AgentOutput,
    CollaborationStrategy,
    SynthesisResult,
    calculate_consensus_confidence,
    calculate_vote_distribution,
)

# Constants
WEAK_CONSENSUS_CONFIDENCE_PENALTY = 0.7  # Reduce confidence by 30% for weak consensus
MIN_CONSENSUS_DEFAULT = 0.51  # Default minimum consensus threshold (>50%)
PERCENT_TO_FRACTION = 0.01  # Convert percentage to fraction


class ConsensusStrategy(CollaborationStrategy):
    """Simple majority-voting collaboration strategy.

    Agents vote on decisions, and the option with >50% support wins.
    Confidence is calculated based on:
    - Consensus strength (% of agents agreeing)
    - Average confidence of supporting agents

    Configuration:
        min_agents (int): Minimum agents required (default: 1)
        min_consensus (float): Minimum consensus % (default: 0.51)
        tie_breaker (str): "confidence" | "first" (default: "confidence")

    Capabilities:
        - Single-round voting (no debate)
        - Equal weight per agent (no merit weighting)
        - Handles partial participation
        - Deterministic results
        - Requires conflict resolver for weak consensus

    Example:
        >>> strategy = ConsensusStrategy()
        >>> outputs = [
        ...     AgentOutput("a1", "yes", "reason1", 0.9, {}),
        ...     AgentOutput("a2", "yes", "reason2", 0.8, {}),
        ...     AgentOutput("a3", "no", "reason3", 0.7, {})
        ... ]
        >>> result = strategy.synthesize(outputs, {})
        >>> result.decision
        'yes'
        >>> result.votes
        {'yes': 2, 'no': 1}
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
            ValueError: If agent_outputs is invalid or too few agents
            RuntimeError: If synthesis fails unexpectedly

        Example:
            >>> outputs = [AgentOutput("a1", "yes", "r1", 0.9, {})]
            >>> result = strategy.synthesize(outputs, {})
            >>> result.decision
            'yes'
        """
        # Validate inputs
        self.validate_inputs(agent_outputs)

        # Get config
        min_agents = config.get("min_agents", 1)
        min_consensus = config.get("min_consensus", PROB_MEDIUM + PERCENT_TO_FRACTION)  # >50% (0.51)
        tie_breaker = config.get("tie_breaker", "confidence")

        # Validate config
        if not 0 <= min_consensus <= 1:
            raise ValueError(
                f"min_consensus must be between 0 and 1, got {min_consensus}"
            )
        if tie_breaker not in ["confidence", "first"]:
            raise ValueError(
                f"tie_breaker must be 'confidence' or 'first', got '{tie_breaker}'"
            )

        # Check minimum agents
        if len(agent_outputs) < min_agents:
            raise ValueError(
                f"Need at least {min_agents} agents, got {len(agent_outputs)}"
            )

        # Count votes (preserve decision types, don't convert to strings)
        vote_counts = calculate_vote_distribution(agent_outputs)
        total_votes = len(agent_outputs)

        # Get decisions sorted by vote count (highest first)
        sorted_decisions = sorted(
            vote_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )

        if not sorted_decisions:
            raise RuntimeError("No votes found")

        # Check for tie (multiple decisions with same count)
        max_count = sorted_decisions[0][1]
        tied_decisions = [d for d, count in sorted_decisions if count == max_count]

        if len(tied_decisions) > 1:
            # Tie detected - use tie-breaking
            decision = self._break_tie(tied_decisions, agent_outputs, tie_breaker)
        else:
            decision = sorted_decisions[0][0]

        # Check if we have majority (>50%)
        decision_support = vote_counts[decision] / total_votes

        if decision_support < min_consensus:
            # No clear majority - create conflict
            conflicts = self.detect_conflicts(agent_outputs, threshold=PROB_LOW_MEDIUM)
            return SynthesisResult(
                decision=decision,  # Best effort decision
                confidence=round(decision_support * WEAK_CONSENSUS_CONFIDENCE_PENALTY, 4),  # noqa: Standard precision
                method="consensus_weak",
                votes=vote_counts,
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

        # Calculate confidence using utility function
        confidence = calculate_consensus_confidence(agent_outputs, decision)

        # Get supporting and dissenting agents
        supporters = [o.agent_name for o in agent_outputs if o.decision == decision]
        dissenters = [o.agent_name for o in agent_outputs if o.decision != decision]

        # Detect conflicts
        conflicts = self.detect_conflicts(agent_outputs, threshold=PROB_LOW_MEDIUM)

        # Build reasoning
        reasoning = self._build_reasoning(
            decision, decision_support, supporters, dissenters, vote_counts
        )

        return SynthesisResult(
            decision=decision,
            confidence=confidence,
            method="consensus",
            votes=vote_counts,
            conflicts=conflicts,
            reasoning=reasoning,
            metadata={
                "total_agents": total_votes,
                "supporters": supporters,
                "dissenters": dissenters,
                "decision_support": decision_support,
                "avg_supporter_confidence": sum(
                    o.confidence for o in agent_outputs if o.decision == decision
                ) / len(supporters) if supporters else 0.0
            }
        )

    def _break_tie(
        self,
        tied_decisions: List[Any],
        agent_outputs: List[AgentOutput],
        method: str = "confidence"
    ) -> Any:
        """Break tie between decisions with equal votes.

        Args:
            tied_decisions: List of decisions that are tied
            agent_outputs: All agent outputs
            method: Tie-breaking method ("confidence" or "first")

        Returns:
            Winning decision (preserves original decision type)

        Example:
            >>> # Two agents vote for different options with equal counts
            >>> outputs = [
            ...     AgentOutput("a1", "Option A", "r1", 0.9, {}),
            ...     AgentOutput("a2", "Option B", "r2", 0.7, {})
            ... ]
            >>> # Option A wins due to higher confidence (0.9 vs 0.7)
            >>> strategy._break_tie(["Option A", "Option B"], outputs, "confidence")
            'Option A'
        """
        if method == "first":
            # Return first decision in vote order
            return tied_decisions[0]

        # Confidence-based: highest average confidence wins
        decision_confidences = {}
        for decision in tied_decisions:
            supporters = [
                o for o in agent_outputs
                if o.decision == decision
            ]
            # Defensive check: if no supporters, assign 0 confidence
            if not supporters:
                decision_confidences[decision] = 0.0
            else:
                avg_confidence = sum(o.confidence for o in supporters) / len(supporters)
                decision_confidences[decision] = avg_confidence

        # Return decision with highest confidence
        return max(decision_confidences.items(), key=lambda x: x[1])[0]

    def _build_reasoning(
        self,
        decision: Any,
        support_pct: float,
        supporters: List[str],
        dissenters: List[str],
        vote_counts: Dict[Any, int]
    ) -> str:
        """Build human-readable reasoning for decision.

        Args:
            decision: Final decision
            support_pct: Percentage of agents supporting decision
            supporters: List of supporting agent names
            dissenters: List of dissenting agent names
            vote_counts: Vote count breakdown

        Returns:
            Reasoning string with vote breakdown and participation details

        Example:
            >>> reasoning = strategy._build_reasoning(
            ...     "Option A", 0.667,
            ...     ["agent1", "agent2"],
            ...     ["agent3"],
            ...     {"Option A": 2, "Option B": 1}
            ... )
            >>> "66.7% support" in reasoning
            True
            >>> "agent1, agent2" in reasoning
            True
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
        """Get strategy capabilities for feature detection.

        Returns:
            Dict of capability flags indicating what this strategy supports

        Example:
            >>> caps = strategy.get_capabilities()
            >>> caps["supports_debate"]
            False
            >>> caps["deterministic"]
            True
        """
        return {
            "supports_debate": False,  # Single-round voting only
            "supports_convergence": False,  # No multi-round
            "supports_merit_weighting": False,  # Equal weight per agent
            "supports_partial_participation": True,  # Can handle missing agents
            "supports_async": False,  # Sync only for now
            "deterministic": True,  # Same input -> same output
            "requires_conflict_resolver": True  # Needs resolver for weak consensus
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Get strategy metadata for introspection.

        Returns:
            Strategy metadata including name, version, description, and config schema

        Example:
            >>> metadata = strategy.get_metadata()
            >>> metadata["name"]
            'ConsensusStrategy'
            >>> "min_consensus" in metadata["config_schema"]
            True
        """
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
                    "default": MIN_CONSENSUS_DEFAULT,
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
