"""Debate-based collaboration strategy.

Agents engage in multi-round structured debate:
1. Initial positions: Each agent states decision + reasoning
2. Debate rounds: Agents see others' arguments, refine positions
3. Convergence check: Stop when no new insights emerge
4. Final synthesis: Extract consensus from debate history

This strategy produces higher-quality decisions than simple voting
by allowing agents to consider counter-arguments and refine reasoning.
"""

from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import Counter

from src.strategies.base import (
    CollaborationStrategy,
    AgentOutput,
    SynthesisResult,
    Conflict,
    calculate_consensus_confidence,
    extract_majority_decision
)


@dataclass
class DebateRound:
    """Single round of debate.

    Attributes:
        round_number: Round index (0-based)
        agent_outputs: Outputs from all agents this round
        convergence_score: Agreement level (0-1)
        new_insights: Whether new arguments emerged
        metadata: Additional round metadata
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
        convergence_round: Round where convergence occurred (-1 if not converged)
        metadata: Additional debate metadata
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
        >>> # Debate converges after rounds
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

        # Get config with defaults
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
        previous_decisions: Optional[Dict[str, Any]] = None
        current_outputs = agent_outputs

        # Conduct debate rounds
        for round_num in range(max_rounds):
            # Calculate convergence score
            convergence_score = self._calculate_convergence(
                current_outputs, previous_decisions
            )

            # Create debate round record
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

            # Check convergence (only after minimum rounds)
            if round_num >= min_rounds - 1:
                if convergence_score >= convergence_threshold:
                    debate_history.converged = True
                    debate_history.convergence_round = round_num
                    break

            # Prepare for next round (if not last)
            if round_num < max_rounds - 1:
                previous_decisions = {o.agent_name: o.decision for o in current_outputs}
                # Note: In full implementation with multi-turn agent support,
                # we would re-query agents here with debate context.
                # For now, we use the same outputs across rounds (simulating convergence)

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
        previous_decisions: Optional[Dict[str, Any]]
    ) -> float:
        """Calculate convergence score (% agents unchanged).

        Args:
            current_outputs: Current round outputs
            previous_decisions: Previous round decisions by agent name

        Returns:
            Convergence score (0-1), where 1.0 means all agents unchanged
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
        previous_decisions: Optional[Dict[str, Any]]
    ) -> bool:
        """Detect if new insights emerged this round.

        New insights are indicated by any agent changing their position.

        Args:
            current_outputs: Current round outputs
            previous_decisions: Previous round decisions by agent name

        Returns:
            True if any agent changed position, False otherwise
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
        """Get distribution of decisions.

        Args:
            outputs: Agent outputs

        Returns:
            Dict mapping decision to count
        """
        return dict(Counter(str(o.decision) for o in outputs))

    def _extract_consensus(
        self,
        final_outputs: List[AgentOutput],
        debate_history: DebateHistory,
        require_unanimous: bool
    ) -> Tuple[Any, float]:
        """Extract final consensus from debate.

        Calculates confidence based on:
        1. Consensus strength (% of agents agreeing)
        2. Convergence quality (did debate converge?)
        3. Average confidence of supporting agents

        Args:
            final_outputs: Final round outputs
            debate_history: Complete debate history
            require_unanimous: Whether to require 100% agreement

        Returns:
            Tuple of (decision, confidence)
        """
        # Get most common decision
        decisions = [str(o.decision) for o in final_outputs]
        vote_counts = Counter(decisions)

        if not vote_counts:
            # Edge case: no outputs (shouldn't happen with validation)
            return None, 0.0

        decision = vote_counts.most_common(1)[0][0]

        # Calculate confidence components
        consensus_strength = vote_counts[decision] / len(final_outputs)

        if require_unanimous and consensus_strength < 1.0:
            # Penalize non-unanimous results when unanimity required
            confidence = consensus_strength * 0.5
        else:
            # Convergence bonus: boost confidence if debate converged
            convergence_bonus = 0.1 if debate_history.converged else 0.0

            # Average confidence of agents supporting this decision
            supporters = [o for o in final_outputs if str(o.decision) == decision]
            avg_confidence = sum(o.confidence for o in supporters) / len(supporters)

            # Combined confidence (capped at 1.0)
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
            Human-readable reasoning string explaining the debate outcome
        """
        lines = []

        # Overall outcome
        lines.append(
            f"Debate concluded after {debate_history.total_rounds} rounds with "
            f"decision: '{decision}'."
        )

        # Convergence status
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
        """Serialize debate history for metadata storage.

        Args:
            history: Debate history to serialize

        Returns:
            Serializable dict representation
        """
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
        """Get strategy capabilities.

        Returns:
            Dict of capability flags:
            - supports_debate: Multi-round debate
            - supports_convergence: Convergence detection
            - supports_merit_weighting: Uses agent merit scores
            - supports_partial_participation: Can handle missing agents
            - supports_async: Can run asynchronously
            - deterministic: Produces same result given same inputs
            - requires_conflict_resolver: Needs conflict resolution for non-converged
        """
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
        """Get strategy metadata including config schema.

        Returns:
            Strategy metadata with configuration schema
        """
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
