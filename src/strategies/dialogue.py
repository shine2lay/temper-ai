"""Dialogue-based collaboration strategy with multi-round agent re-invocation.

This strategy implements true multi-agent dialogue where agents are re-invoked
across multiple rounds with accumulated dialogue history as context:
- Round 1: Agents execute independently (initial positions)
- Round 2+: Agents receive dialogue_history showing prior agent outputs
- Convergence detection: Stop early if agents stabilize
- Cost tracking: Accumulate per-round costs, enforce budget
- Final synthesis: Use consensus on last round outputs

Design Philosophy:
- Transform from post-hoc voting to actual back-and-forth dialogue
- Agents can respond to each other's positions across rounds
- Early stopping via convergence detection saves costs
- Backward compatible: Opt-in via dialogue_mode config flag
- Observability first: Track full dialogue transcript and metadata

Example:
    >>> from src.strategies.dialogue import DialogueOrchestrator
    >>> from src.strategies.base import AgentOutput
    >>>
    >>> strategy = DialogueOrchestrator(max_rounds=3, cost_budget_usd=10.0)
    >>> # Round 1: Agents execute independently
    >>> round1_outputs = [
    ...     AgentOutput("architect", "Option A", "reasoning...", 0.8, {"cost_usd": 0.5}),
    ...     AgentOutput("critic", "Option B", "counter-reasoning...", 0.75, {"cost_usd": 0.5})
    ... ]
    >>> # Round 2+: Executor re-invokes agents with dialogue history
    >>> # (handled by executor integration in Phase 1.3-1.4)
    >>> final_result = strategy.synthesize(round1_outputs, {})
    >>> final_result.decision  # Consensus from final round
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from src.strategies.base import (
    CollaborationStrategy,
    AgentOutput,
    SynthesisResult
)


@dataclass
class DialogueRound:
    """Single round of agent dialogue.

    Tracks all outputs from one round of the dialogue, along with
    convergence metrics and cost information.

    Attributes:
        round_number: Zero-indexed round number (0 = first round)
        agent_outputs: All agent outputs from this round
        convergence_score: Similarity between this round and previous (0.0-1.0)
        position_stability_score: Percentage of agents with unchanged positions
        new_insights: Whether new information emerged this round
        round_cost_usd: Total cost for this round (sum of agent costs)
        cumulative_cost_usd: Total cost up to and including this round
        metadata: Additional round-specific information

    Example:
        >>> round = DialogueRound(
        ...     round_number=0,
        ...     agent_outputs=[output1, output2],
        ...     convergence_score=0.0,  # No prior round to compare
        ...     position_stability_score=0.0,
        ...     new_insights=True,
        ...     round_cost_usd=1.0,
        ...     cumulative_cost_usd=1.0,
        ...     metadata={"duration_seconds": 5.2}
        ... )
    """
    round_number: int
    agent_outputs: List[AgentOutput]
    convergence_score: float = 0.0
    position_stability_score: float = 0.0
    new_insights: bool = True
    round_cost_usd: float = 0.0
    cumulative_cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DialogueHistory:
    """Complete dialogue transcript across all rounds.

    Tracks the full history of a multi-round dialogue session,
    including all rounds, convergence status, and final statistics.

    Attributes:
        rounds: List of all dialogue rounds (ordered by round_number)
        total_rounds: Total number of rounds executed
        converged: Whether dialogue converged before max_rounds
        convergence_round: Round number where convergence occurred (0 if not converged)
        early_stop_reason: Why dialogue stopped early ("convergence", "budget", "max_rounds", None)
        total_cost_usd: Total cost across all rounds
        agent_participation: Dict mapping agent name to number of rounds participated

    Example:
        >>> history = DialogueHistory(
        ...     rounds=[round1, round2, round3],
        ...     total_rounds=3,
        ...     converged=True,
        ...     convergence_round=2,
        ...     early_stop_reason="convergence",
        ...     total_cost_usd=3.0,
        ...     agent_participation={"agent1": 3, "agent2": 3}
        ... )
    """
    rounds: List[DialogueRound] = field(default_factory=list)
    total_rounds: int = 0
    converged: bool = False
    convergence_round: int = 0
    early_stop_reason: Optional[str] = None  # "convergence", "budget", "max_rounds"
    total_cost_usd: float = 0.0
    agent_participation: Dict[str, int] = field(default_factory=dict)


class DialogueOrchestrator(CollaborationStrategy):
    """Multi-round dialogue collaboration strategy.

    Enables true agent dialogue by requiring executors to re-invoke agents
    across multiple rounds. Each round, agents receive accumulated dialogue
    history as context, allowing them to respond to each other's positions.

    This strategy sets requires_requery=True to signal executors that they
    should use multi-round execution mode instead of one-shot synthesis.

    Configuration:
        max_rounds: Maximum dialogue rounds (default: 3)
        convergence_threshold: Similarity threshold for early stopping (default: 0.85)
        cost_budget_usd: Maximum cost in USD, None for unlimited (default: None)
        min_rounds: Minimum rounds before convergence check (default: 1)

    Note:
        Phase 1 implementation (this file) provides core data structures and
        interface contracts. Actual dialogue execution logic (agent re-invocation,
        dialogue history propagation) is implemented in executor integration
        (Phase 1.3-1.4, parallel.py and sequential.py).

    Example:
        >>> strategy = DialogueOrchestrator(
        ...     max_rounds=3,
        ...     convergence_threshold=0.85,
        ...     cost_budget_usd=10.0,
        ...     min_rounds=2
        ... )
        >>> strategy.requires_requery  # Signals executor for multi-round mode
        True
        >>> # Executor will re-invoke agents up to max_rounds times
        >>> # Final synthesis uses consensus on last round outputs
    """

    def __init__(
        self,
        max_rounds: int = 3,
        convergence_threshold: float = 0.85,
        cost_budget_usd: Optional[float] = None,
        min_rounds: int = 1
    ):
        """Initialize dialogue orchestrator.

        Args:
            max_rounds: Maximum number of dialogue rounds (must be >= 1)
            convergence_threshold: Threshold for convergence detection (0.0-1.0)
            cost_budget_usd: Cost budget in USD, None for unlimited
            min_rounds: Minimum rounds before allowing convergence (must be >= 1)

        Raises:
            ValueError: If max_rounds < 1 or min_rounds < 1 or convergence_threshold not in [0, 1]
        """
        if max_rounds < 1:
            raise ValueError(f"max_rounds must be >= 1, got {max_rounds}")
        if min_rounds < 1:
            raise ValueError(f"min_rounds must be >= 1, got {min_rounds}")
        if not 0 <= convergence_threshold <= 1:
            raise ValueError(
                f"convergence_threshold must be in [0, 1], got {convergence_threshold}"
            )
        if cost_budget_usd is not None and cost_budget_usd <= 0:
            raise ValueError(f"cost_budget_usd must be > 0, got {cost_budget_usd}")

        self.max_rounds = max_rounds
        self.convergence_threshold = convergence_threshold
        self.cost_budget_usd = cost_budget_usd
        self.min_rounds = min_rounds

    @property
    def requires_requery(self) -> bool:
        """Signal to executor: I need multi-round execution with agent re-invocation.

        When True, executors should:
        1. Execute agents normally in round 1
        2. For round 2+, re-invoke agents with dialogue_history in input_data
        3. Continue until max_rounds or early stop conditions
        4. Call synthesize() with final round outputs

        Returns:
            True: DialogueOrchestrator always requires multi-round execution
        """
        return True

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Final synthesis from last dialogue round outputs.

        This method is called by executors after all dialogue rounds complete.
        It uses consensus strategy logic to synthesize the final decision from
        the last round's agent outputs.

        Args:
            agent_outputs: Agent outputs from the final dialogue round
            config: Collaboration configuration (passed to consensus strategy)

        Returns:
            SynthesisResult with final synthesized decision

        Raises:
            ValueError: If agent_outputs is empty

        Note:
            This is a simplified Phase 1 implementation. Phase 2+ may add
            custom synthesis logic that considers full dialogue history.
        """
        # Validate inputs
        self.validate_inputs(agent_outputs)

        # Use consensus strategy for final synthesis
        # (avoids code duplication, provides consistent synthesis)
        from src.strategies.consensus import ConsensusStrategy
        consensus = ConsensusStrategy()
        result = consensus.synthesize(agent_outputs, config)

        # Add dialogue-specific metadata
        result.metadata["strategy"] = "dialogue"
        result.metadata["synthesis_method"] = "consensus_from_final_round"

        return result

    def get_capabilities(self) -> Dict[str, bool]:
        """Get dialogue orchestrator capabilities.

        Returns:
            Dict of capability flags:
            - supports_debate: True (multi-round dialogue)
            - supports_convergence: True (Phase 2+)
            - supports_merit_weighting: False (uses consensus)
            - supports_partial_participation: False
            - supports_async: False (Phase 1)
            - supports_streaming: False
        """
        return {
            "supports_debate": True,
            "supports_convergence": True,  # Phase 2
            "supports_merit_weighting": False,
            "supports_partial_participation": False,
            "supports_async": False,
            "supports_streaming": False
        }
