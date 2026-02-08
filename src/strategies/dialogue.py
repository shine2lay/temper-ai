"""Dialogue-based collaboration strategy with multi-round agent re-invocation.

This strategy implements true multi-agent dialogue where agents are re-invoked
across multiple rounds with accumulated dialogue history as context:
- Round 1: Agents execute independently (initial positions)
- Round 2+: Agents receive dialogue_history showing prior agent outputs
- Convergence detection: Stop early if agents stabilize
- Cost tracking: Accumulate per-round costs, enforce budget
- Final synthesis: Use consensus on last round outputs
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.constants.limits import SMALL_ITEM_LIMIT
from src.constants.probabilities import PROB_CRITICAL
from src.strategies._dialogue_helpers import (
    build_merit_weighted_reasoning,
    calculate_exact_match_convergence,
    calculate_semantic_similarity,
    curate_recent,
    curate_relevant,
    get_merit_weights,
    merit_weighted_synthesis,
)
from src.strategies.base import AgentOutput, CollaborationStrategy, SynthesisResult
from src.strategies.constants import DEFAULT_MAX_ROUNDS, DEFAULT_MIN_ROUNDS

logger = logging.getLogger(__name__)


@dataclass
class DialogueRound:
    """Single round of agent dialogue.

    Tracks all outputs from one round of the dialogue, along with
    convergence metrics and cost information.
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
        use_semantic_convergence: Use semantic similarity instead of exact match (default: True)
        context_strategy: How to propagate dialogue history (default: "full")
        context_window_size: For "recent" strategy, how many recent rounds (default: 2)
        use_merit_weighting: Weight agent opinions by historical performance (default: False)
        merit_domain: Domain for merit score lookup (default: None)
    """

    # Class-level singleton for SentenceTransformer model.
    _embedding_model: Any = None
    _embedding_model_loaded: bool = False

    @classmethod
    def warm_up(cls) -> bool:
        """Preload the SentenceTransformer model for semantic convergence.

        Returns:
            True if model was loaded successfully, False otherwise.
        """
        try:
            from sentence_transformers import SentenceTransformer
            if not cls._embedding_model_loaded:
                logger.info("Loading sentence-transformers model (paraphrase-MiniLM-L6-v2)...")
                cls._embedding_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
                cls._embedding_model_loaded = True
            return True
        except ImportError:
            logger.warning(
                "sentence-transformers not available for warm_up. "
                "Install with: pip install sentence-transformers"
            )
            return False
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning(f"Failed to warm up embedding model: {e}")
            return False

    @classmethod
    def _get_embedding_model(cls) -> Any:
        """Get or lazily load the class-level SentenceTransformer model."""
        if not cls._embedding_model_loaded:
            cls.warm_up()
        return cls._embedding_model

    def __init__(
        self,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        convergence_threshold: float = PROB_CRITICAL,
        cost_budget_usd: Optional[float] = None,
        min_rounds: int = DEFAULT_MIN_ROUNDS,
        use_semantic_convergence: bool = True,
        context_strategy: str = "full",
        context_window_size: int = SMALL_ITEM_LIMIT - 3,  # 2 rounds
        use_merit_weighting: bool = False,
        merit_domain: Optional[str] = None
    ):
        """Initialize dialogue orchestrator.

        Args:
            max_rounds: Maximum number of dialogue rounds (must be >= 1)
            convergence_threshold: Threshold for convergence detection (0.0-1.0)
            cost_budget_usd: Cost budget in USD, None for unlimited
            min_rounds: Minimum rounds before allowing convergence (must be >= 1)
            use_semantic_convergence: Use semantic similarity instead of exact match
            context_strategy: Context propagation strategy - "full", "recent", "relevant"
            context_window_size: For "recent" strategy, number of recent rounds to include
            use_merit_weighting: Weight agent opinions by historical performance
            merit_domain: Domain for merit score lookup

        Raises:
            ValueError: If parameters are invalid
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
        if context_strategy not in ["full", "recent", "relevant"]:
            raise ValueError(
                f"context_strategy must be 'full', 'recent', or 'relevant', got {context_strategy}"
            )
        if context_window_size < 1:
            raise ValueError(f"context_window_size must be >= 1, got {context_window_size}")

        self.max_rounds = max_rounds
        self.convergence_threshold = convergence_threshold
        self.cost_budget_usd = cost_budget_usd
        self.min_rounds = min_rounds
        self.use_semantic_convergence = use_semantic_convergence
        self.context_strategy = context_strategy
        self.context_window_size = context_window_size
        self.use_merit_weighting = use_merit_weighting
        self.merit_domain = merit_domain
        self._embeddings_available = None  # Lazy check for sentence-transformers

    @property
    def requires_requery(self) -> bool:
        """Signal to executor: I need multi-round execution with agent re-invocation."""
        return True

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Final synthesis from last dialogue round outputs.

        Args:
            agent_outputs: Agent outputs from the final dialogue round
            config: Collaboration configuration

        Returns:
            SynthesisResult with final synthesized decision

        Raises:
            ValueError: If agent_outputs is empty
        """
        self.validate_inputs(agent_outputs)

        if self.use_merit_weighting:
            result = merit_weighted_synthesis(agent_outputs, self.merit_domain)
            result.metadata["synthesis_method"] = "merit_weighted"
        else:
            from src.strategies.consensus import ConsensusStrategy
            consensus = ConsensusStrategy()
            result = consensus.synthesize(agent_outputs, config)
            result.metadata["synthesis_method"] = "consensus_from_final_round"

        result.metadata["strategy"] = "dialogue"
        return result

    def curate_dialogue_history(
        self,
        dialogue_history: List[Dict[str, Any]],
        current_round: int,
        agent_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Curate dialogue history based on context strategy.

        Args:
            dialogue_history: Full dialogue history
            current_round: Current round number
            agent_name: Name of agent receiving the history (for relevance filtering)

        Returns:
            Curated dialogue history based on context_strategy
        """
        if not dialogue_history:
            return []

        if self.context_strategy == "full":
            return dialogue_history
        elif self.context_strategy == "recent":
            return curate_recent(dialogue_history, current_round, self.context_window_size)
        elif self.context_strategy == "relevant":
            return curate_relevant(dialogue_history, agent_name, self.context_window_size)
        else:
            logger.warning(f"Unknown context_strategy '{self.context_strategy}', using 'full'")
            return dialogue_history

    def _check_embeddings_available(self) -> bool:
        """Check if sentence-transformers is available for semantic convergence."""
        if self._embeddings_available is not None:
            return self._embeddings_available

        try:
            import sentence_transformers  # noqa: F401
            self._embeddings_available = True
            logger.debug("sentence-transformers available for semantic convergence")
        except ImportError:
            self._embeddings_available = False
            logger.warning(
                "sentence-transformers not available, falling back to exact match convergence. "
                "Install with: pip install sentence-transformers"
            )

        return self._embeddings_available

    def calculate_convergence(
        self,
        current_outputs: List[AgentOutput],
        previous_outputs: List[AgentOutput]
    ) -> float:
        """Calculate convergence score between current and previous round outputs.

        Args:
            current_outputs: Outputs from current round
            previous_outputs: Outputs from previous round

        Returns:
            Convergence score (0.0-1.0)
        """
        if not previous_outputs:
            return 0.0

        if self.use_semantic_convergence:
            if self._check_embeddings_available():
                try:
                    return calculate_semantic_similarity(
                        current_outputs, previous_outputs, self._get_embedding_model
                    )
                except (ImportError, RuntimeError, ValueError, TypeError) as e:
                    logger.warning(
                        f"Semantic similarity calculation failed: {e}. "
                        f"Falling back to exact match."
                    )

        return calculate_exact_match_convergence(current_outputs, previous_outputs)

    def _get_merit_weights(self, agent_outputs: List[AgentOutput]) -> Dict[str, float]:
        """Get merit weights for each agent. Delegates to helper."""
        return get_merit_weights(agent_outputs, self.merit_domain)

    def _merit_weighted_synthesis(
        self, agent_outputs: List[AgentOutput], config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize using merit-weighted voting. Delegates to helper."""
        return merit_weighted_synthesis(agent_outputs, self.merit_domain)

    def _build_merit_weighted_reasoning(
        self, decision: Any, support: float, agent_outputs: List[AgentOutput],
        merit_weights: Dict[str, float], weighted_votes: Dict[Any, float],
    ) -> str:
        """Build reasoning for merit-weighted synthesis. Delegates to helper."""
        return build_merit_weighted_reasoning(
            decision, support, agent_outputs, merit_weights, weighted_votes
        )

    def _curate_recent(
        self, dialogue_history: List[Dict[str, Any]], current_round: int
    ) -> List[Dict[str, Any]]:
        """Curate history to recent rounds. Delegates to helper."""
        return curate_recent(dialogue_history, current_round, self.context_window_size)

    def _curate_relevant(
        self, dialogue_history: List[Dict[str, Any]], agent_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Curate history to relevant entries. Delegates to helper."""
        return curate_relevant(dialogue_history, agent_name, self.context_window_size)

    def _calculate_exact_match_convergence(
        self, current_outputs: List[AgentOutput], previous_outputs: List[AgentOutput]
    ) -> float:
        """Calculate exact match convergence. Delegates to helper."""
        return calculate_exact_match_convergence(current_outputs, previous_outputs)

    def _calculate_semantic_similarity(
        self, current_outputs: List[AgentOutput], previous_outputs: List[AgentOutput]
    ) -> float:
        """Calculate semantic similarity convergence. Delegates to helper."""
        return calculate_semantic_similarity(
            current_outputs, previous_outputs, self._get_embedding_model
        )

    def get_capabilities(self) -> Dict[str, bool]:
        """Get dialogue orchestrator capabilities.

        Returns:
            Dict of capability flags
        """
        return {
            "supports_debate": True,
            "supports_convergence": True,
            "supports_merit_weighting": True,
            "supports_partial_participation": False,
            "supports_async": False,
            "supports_streaming": False
        }
