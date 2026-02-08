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

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.constants.limits import SMALL_ITEM_LIMIT
from src.constants.probabilities import PROB_CRITICAL, PROB_MEDIUM, PROB_VERY_HIGH_PLUS
from src.strategies.base import AgentOutput, CollaborationStrategy, SynthesisResult
from src.strategies.constants import DEFAULT_MAX_ROUNDS, DEFAULT_MIN_ROUNDS

logger = logging.getLogger(__name__)


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
        use_semantic_convergence: Use semantic similarity instead of exact match (default: True)
        context_strategy: How to propagate dialogue history - "full", "recent", "relevant" (default: "full")
        context_window_size: For "recent" strategy, how many recent rounds to include (default: 2)
        use_merit_weighting: Weight agent opinions by historical performance (default: False)
        merit_domain: Domain for merit score lookup, None for agent name (default: None)

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

    # Class-level singleton for SentenceTransformer model.
    # Loaded lazily on first use via _get_embedding_model() and cached here
    # so all instances share the same (expensive) model object.
    _embedding_model: Any = None
    _embedding_model_loaded: bool = False

    @classmethod
    def warm_up(cls) -> bool:
        """Preload the SentenceTransformer model for semantic convergence.

        Call this during application startup to avoid latency on first
        convergence check. Safe to call multiple times (no-op if already loaded).

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
        """Get or lazily load the class-level SentenceTransformer model.

        Returns:
            SentenceTransformer model instance.
        """
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
            use_semantic_convergence: Use semantic similarity instead of exact match (default: True)
            context_strategy: Context propagation strategy - "full", "recent", "relevant" (default: "full")
            context_window_size: For "recent" strategy, number of recent rounds to include (default: 2)
            use_merit_weighting: Weight agent opinions by historical performance (default: False)
            merit_domain: Domain for merit score lookup, None uses agent name as domain (default: None)

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
        If merit weighting is enabled, uses merit scores to weight agent opinions.
        Otherwise, uses consensus strategy for equal-weight voting.

        Args:
            agent_outputs: Agent outputs from the final dialogue round
            config: Collaboration configuration

        Returns:
            SynthesisResult with final synthesized decision

        Raises:
            ValueError: If agent_outputs is empty
        """
        # Validate inputs
        self.validate_inputs(agent_outputs)

        # Use merit-weighted synthesis if enabled
        if self.use_merit_weighting:
            result = self._merit_weighted_synthesis(agent_outputs, config)
            result.metadata["synthesis_method"] = "merit_weighted"
        else:
            # Use consensus strategy for equal-weight synthesis
            from src.strategies.consensus import ConsensusStrategy
            consensus = ConsensusStrategy()
            result = consensus.synthesize(agent_outputs, config)
            result.metadata["synthesis_method"] = "consensus_from_final_round"

        # Add dialogue-specific metadata
        result.metadata["strategy"] = "dialogue"

        return result

    def _get_merit_weights(self, agent_outputs: List[AgentOutput]) -> Dict[str, float]:
        """Get merit weights for each agent from observability tracker.

        Queries AgentMeritScore from observability database and converts to weights.
        Falls back to equal weights (1.0) if scores unavailable.

        Args:
            agent_outputs: Agent outputs to get weights for

        Returns:
            Dict mapping agent_name to weight (0.0-1.0+)
        """
        weights = {}

        try:
            # Try to import and query observability tracker (public API)
            from sqlmodel import select

            from src.observability import AgentMeritScore, ExecutionTracker

            tracker = ExecutionTracker()
            if not tracker.backend:
                logger.debug("Observability tracker not initialized, using equal weights")
                return {out.agent_name: 1.0 for out in agent_outputs}

            with tracker.backend.get_session_context() as session:
                for output in agent_outputs:
                    agent_name = output.agent_name
                    domain = self.merit_domain or agent_name  # Default to agent name as domain

                    # Query merit score
                    statement = select(AgentMeritScore).where(
                        AgentMeritScore.agent_name == agent_name,
                        AgentMeritScore.domain == domain
                    )
                    merit_score = session.exec(statement).first()

                    if merit_score and merit_score.expertise_score is not None:
                        # Use expertise_score as weight (0.0-1.0+)
                        weights[agent_name] = merit_score.expertise_score
                        logger.debug(
                            f"Merit weight for {agent_name} in {domain}: "
                            f"{merit_score.expertise_score:.3f}"
                        )
                    elif merit_score and merit_score.success_rate is not None:
                        # Fallback to success_rate
                        weights[agent_name] = merit_score.success_rate
                        logger.debug(
                            f"Merit weight for {agent_name} (success_rate): "
                            f"{merit_score.success_rate:.3f}"
                        )
                    else:
                        # No merit score available, use neutral weight
                        weights[agent_name] = PROB_MEDIUM  # Neutral for new agents
                        logger.debug(f"No merit score for {agent_name}, using neutral weight {PROB_MEDIUM}")

        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.warning(f"Failed to load merit scores: {e}. Using equal weights.")
            weights = {out.agent_name: 1.0 for out in agent_outputs}

        # Ensure all agents have weights
        for output in agent_outputs:
            if output.agent_name not in weights:
                weights[output.agent_name] = 1.0

        return weights

    def _merit_weighted_synthesis(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize decision using merit-weighted voting.

        Higher-merit agents have more influence on the final decision.
        Merit scores are multiplied by confidence to get weighted votes.

        Args:
            agent_outputs: Agent outputs from final round
            config: Configuration (unused currently)

        Returns:
            SynthesisResult with merit-weighted decision
        """
        from collections import defaultdict

        from src.strategies.base import Conflict

        # Get merit weights
        merit_weights = self._get_merit_weights(agent_outputs)

        # Calculate weighted votes
        weighted_votes = defaultdict(float)
        agent_votes = {}  # Track which agents voted for what

        for output in agent_outputs:
            decision = output.decision
            agent_name = output.agent_name
            confidence = output.confidence
            merit_weight = merit_weights.get(agent_name, 1.0)

            # Weight = merit_score × confidence
            vote_weight = merit_weight * confidence
            weighted_votes[decision] += vote_weight
            agent_votes[agent_name] = decision

        # Find winning decision (highest weighted vote)
        if not weighted_votes:
            raise ValueError("No votes recorded")

        winning_decision = max(weighted_votes, key=weighted_votes.get)
        total_weight = sum(weighted_votes.values())
        decision_support = weighted_votes[winning_decision] / total_weight if total_weight > 0 else 0

        # Calculate confidence (weighted average of supporting agents)
        supporting_agents = [
            out for out in agent_outputs if out.decision == winning_decision
        ]
        if supporting_agents:
            # Weight confidence by merit scores
            weighted_conf_sum = sum(
                out.confidence * merit_weights.get(out.agent_name, 1.0)
                for out in supporting_agents
            )
            weight_sum = sum(
                merit_weights.get(out.agent_name, 1.0)
                for out in supporting_agents
            )
            avg_confidence = weighted_conf_sum / weight_sum if weight_sum > 0 else 0
            final_confidence = decision_support * avg_confidence
        else:
            final_confidence = PROB_MEDIUM

        # Build reasoning
        reasoning = self._build_merit_weighted_reasoning(
            winning_decision,
            decision_support,
            agent_outputs,
            merit_weights,
            weighted_votes
        )

        # Detect conflicts
        conflicts = []
        if len(weighted_votes) > 1:
            all_agents = [out.agent_name for out in agent_outputs]
            all_decisions = list(weighted_votes.keys())
            disagreement_score = 1.0 - decision_support

            conflicts.append(Conflict(
                agents=all_agents,
                decisions=all_decisions,
                disagreement_score=disagreement_score,
                context={"weighted_votes": dict(weighted_votes)}
            ))

        # Build metadata
        metadata = {
            "total_agents": len(agent_outputs),
            "decision_support": decision_support,
            "merit_weights": merit_weights,
            "weighted_votes": dict(weighted_votes),
            "supporters": [out.agent_name for out in supporting_agents],
            "dissenters": [out.agent_name for out in agent_outputs if out.decision != winning_decision]
        }

        # Convert weighted votes to integer vote counts for display
        vote_counts = {decision: len([o for o in agent_outputs if o.decision == decision])
                      for decision in weighted_votes.keys()}

        return SynthesisResult(
            decision=winning_decision,
            confidence=final_confidence,
            method="merit_weighted",
            votes=vote_counts,
            conflicts=conflicts,
            reasoning=reasoning,
            metadata=metadata
        )

    def _build_merit_weighted_reasoning(
        self,
        decision: Any,
        support: float,
        agent_outputs: List[AgentOutput],
        merit_weights: Dict[str, float],
        weighted_votes: Dict[Any, float]
    ) -> str:
        """Build reasoning explanation for merit-weighted synthesis.

        Args:
            decision: Winning decision
            support: Decision support (0.0-1.0)
            agent_outputs: All agent outputs
            merit_weights: Merit weights by agent
            weighted_votes: Weighted vote totals by decision

        Returns:
            Human-readable reasoning string
        """
        # Find supporters
        supporters = [out for out in agent_outputs if out.decision == decision]
        supporter_names = [
            f"{out.agent_name} (merit: {merit_weights.get(out.agent_name, 1.0):.2f})"
            for out in supporters
        ]

        reasoning = f"Merit-weighted decision: '{decision}' with {support:.1%} weighted support.\n\n"

        reasoning += f"Supporters ({len(supporters)}/{len(agent_outputs)}): "
        reasoning += ", ".join(supporter_names) + "\n\n"

        # Show weighted vote breakdown
        if len(weighted_votes) > 1:
            reasoning += "Weighted vote breakdown:\n"
            for dec, weight in sorted(weighted_votes.items(), key=lambda x: x[1], reverse=True):
                percentage = (weight / sum(weighted_votes.values())) * 100
                reasoning += f"  - '{dec}': {weight:.2f} ({percentage:.1f}%)\n"

        reasoning += "\nNote: Votes weighted by agent merit scores and confidence."

        return reasoning

    def curate_dialogue_history(
        self,
        dialogue_history: List[Dict[str, Any]],
        current_round: int,
        agent_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Curate dialogue history based on context strategy.

        Reduces context size and noise by selectively propagating history.
        Helps reduce costs and improve focus in long dialogues.

        Args:
            dialogue_history: Full dialogue history
            current_round: Current round number
            agent_name: Name of agent receiving the history (for relevance filtering)

        Returns:
            Curated dialogue history based on context_strategy

        Example:
            >>> strategy = DialogueOrchestrator(context_strategy="recent", context_window_size=2)
            >>> full_history = [round0, round1, round2, round3]  # 4 rounds
            >>> curated = strategy.curate_dialogue_history(full_history, current_round=4)
            >>> len(curated)  # Only last 2 rounds
            2
        """
        if not dialogue_history:
            return []

        if self.context_strategy == "full":
            # Return all history (current behavior)
            return dialogue_history

        elif self.context_strategy == "recent":
            # Return only recent rounds (sliding window)
            return self._curate_recent(dialogue_history, current_round)

        elif self.context_strategy == "relevant":
            # Return history relevant to current agent (keyword-based)
            return self._curate_relevant(dialogue_history, agent_name)

        else:
            # Fallback to full (should not reach here due to validation)
            logger.warning(f"Unknown context_strategy '{self.context_strategy}', using 'full'")
            return dialogue_history

    def _curate_recent(
        self,
        dialogue_history: List[Dict[str, Any]],
        current_round: int
    ) -> List[Dict[str, Any]]:
        """Curate history to recent rounds only (sliding window).

        Args:
            dialogue_history: Full dialogue history
            current_round: Current round number

        Returns:
            Recent rounds only (up to context_window_size)
        """
        # Group by round number
        rounds_dict = {}
        for entry in dialogue_history:
            round_num = entry["round"]
            if round_num not in rounds_dict:
                rounds_dict[round_num] = []
            rounds_dict[round_num].append(entry)

        # Get recent round numbers
        all_rounds = sorted(rounds_dict.keys())
        recent_rounds = all_rounds[-self.context_window_size:] if all_rounds else []

        # Build curated history from recent rounds
        curated = []
        for round_num in recent_rounds:
            curated.extend(rounds_dict[round_num])

        logger.debug(
            f"Context curation (recent): {len(dialogue_history)} entries → "
            f"{len(curated)} entries (last {len(recent_rounds)} rounds)"
        )

        return curated

    def _curate_relevant(
        self,
        dialogue_history: List[Dict[str, Any]],
        agent_name: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Curate history to entries relevant to current agent.

        Uses keyword matching and agent participation to filter relevant history.
        Falls back to recent strategy if agent_name not provided.

        Args:
            dialogue_history: Full dialogue history
            agent_name: Name of current agent

        Returns:
            Relevant history entries
        """
        if not agent_name:
            # Fallback to recent if no agent name
            logger.debug("No agent_name for relevance filtering, using recent strategy")
            return self._curate_recent(dialogue_history, len(dialogue_history))

        # Always include:
        # 1. Latest round (immediate context)
        # 2. Entries mentioning this agent's previous outputs
        # 3. Entries from this agent in prior rounds

        curated = []
        latest_round = max((entry["round"] for entry in dialogue_history), default=0)

        for entry in dialogue_history:
            # Include latest round
            if entry["round"] == latest_round:
                curated.append(entry)
                continue

            # Include agent's own prior contributions
            if entry["agent"] == agent_name:
                curated.append(entry)
                continue

            # Include entries mentioning this agent (simple keyword match)
            reasoning = str(entry.get("reasoning", "")).lower()
            if agent_name.lower() in reasoning:
                curated.append(entry)
                continue

        # Ensure at least some context (fallback to recent if too little)
        if len(curated) < 2:
            logger.debug(
                f"Relevance filtering produced too little context ({len(curated)} entries), "
                f"using recent strategy"
            )
            return self._curate_recent(dialogue_history, len(dialogue_history))

        logger.debug(
            f"Context curation (relevant for {agent_name}): "
            f"{len(dialogue_history)} entries → {len(curated)} entries"
        )

        return curated

    def _check_embeddings_available(self) -> bool:
        """Check if sentence-transformers is available for semantic convergence.

        Returns:
            True if sentence-transformers can be imported, False otherwise
        """
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

    def _calculate_semantic_similarity(
        self,
        current_outputs: List[AgentOutput],
        previous_outputs: List[AgentOutput]
    ) -> float:
        """Calculate semantic similarity between current and previous outputs.

        Uses sentence embeddings to detect when agents express the same idea
        differently (e.g., "Use microservices" vs "Adopt microservice architecture").

        Args:
            current_outputs: Outputs from current round
            previous_outputs: Outputs from previous round

        Returns:
            Similarity score (0.0-1.0): percentage of agents with semantically similar positions
        """
        from sentence_transformers.util import cos_sim

        # Use class-level singleton model (lazy-loaded on first use)
        model = self._get_embedding_model()
        if model is None:
            raise RuntimeError("Failed to load SentenceTransformer model")

        # Map agent names to outputs
        prev_decisions = {out.agent_name: out.decision for out in previous_outputs}
        curr_decisions = {out.agent_name: out.decision for out in current_outputs}

        # Only compare agents present in both rounds
        common_agents = set(prev_decisions.keys()) & set(curr_decisions.keys())
        if not common_agents:
            return 0.0

        # Calculate similarity for each agent
        similar_count = 0
        for agent in common_agents:
            prev_text = str(prev_decisions[agent])
            curr_text = str(curr_decisions[agent])

            # Exact match shortcut
            if prev_text == curr_text:
                similar_count += 1
                continue

            # Calculate semantic similarity
            embeddings = model.encode([prev_text, curr_text])
            similarity = cos_sim(embeddings[0], embeddings[1]).item()

            # Use high threshold (0.9) for semantic similarity
            # This ensures agents truly mean the same thing, not just related ideas
            if similarity >= PROB_VERY_HIGH_PLUS:
                similar_count += 1
                logger.debug(
                    f"Agent {agent} semantically similar: {similarity:.3f} "
                    f"(prev: '{prev_text[:50]}...', curr: '{curr_text[:50]}...')"
                )

        return similar_count / len(common_agents)

    def _calculate_exact_match_convergence(
        self,
        current_outputs: List[AgentOutput],
        previous_outputs: List[AgentOutput]
    ) -> float:
        """Calculate exact match convergence between current and previous outputs.

        Args:
            current_outputs: Outputs from current round
            previous_outputs: Outputs from previous round

        Returns:
            Convergence score (0.0-1.0): percentage of agents with unchanged positions
        """
        # Map agent names to decisions
        prev_decisions = {out.agent_name: out.decision for out in previous_outputs}
        curr_decisions = {out.agent_name: out.decision for out in current_outputs}

        # Only compare agents present in both rounds
        common_agents = set(prev_decisions.keys()) & set(curr_decisions.keys())
        if not common_agents:
            return 0.0

        # Count unchanged positions (exact string match)
        unchanged = sum(
            1 for agent in common_agents
            if str(prev_decisions[agent]) == str(curr_decisions[agent])
        )

        return unchanged / len(common_agents)

    def calculate_convergence(
        self,
        current_outputs: List[AgentOutput],
        previous_outputs: List[AgentOutput]
    ) -> float:
        """Calculate convergence score between current and previous round outputs.

        Uses semantic similarity if use_semantic_convergence is True and
        sentence-transformers is available, otherwise falls back to exact match.

        Args:
            current_outputs: Outputs from current round
            previous_outputs: Outputs from previous round

        Returns:
            Convergence score (0.0-1.0): percentage of agents with similar/unchanged positions

        Example:
            >>> strategy = DialogueOrchestrator(use_semantic_convergence=True)
            >>> current = [AgentOutput("a1", "Use microservices", "r", 0.8, {})]
            >>> previous = [AgentOutput("a1", "Adopt microservice architecture", "r", 0.7, {})]
            >>> score = strategy.calculate_convergence(current, previous)
            >>> # score ≈ 1.0 (semantically similar) vs 0.0 (exact match)
        """
        if not previous_outputs:
            return 0.0  # First round, no convergence yet

        # Try semantic convergence if enabled
        if self.use_semantic_convergence:
            if self._check_embeddings_available():
                try:
                    return self._calculate_semantic_similarity(current_outputs, previous_outputs)
                except (ImportError, RuntimeError, ValueError, TypeError) as e:
                    logger.warning(
                        f"Semantic similarity calculation failed: {e}. "
                        f"Falling back to exact match."
                    )
                    # Fall through to exact match

        # Fall back to exact match
        return self._calculate_exact_match_convergence(current_outputs, previous_outputs)

    def get_capabilities(self) -> Dict[str, bool]:
        """Get dialogue orchestrator capabilities.

        Returns:
            Dict of capability flags:
            - supports_debate: True (multi-round dialogue)
            - supports_convergence: True (Phase 2.1)
            - supports_merit_weighting: True (Phase 2.4)
            - supports_partial_participation: False
            - supports_async: False
            - supports_streaming: False
        """
        return {
            "supports_debate": True,
            "supports_convergence": True,  # Phase 2.1
            "supports_merit_weighting": True,  # Phase 2.4
            "supports_partial_participation": False,
            "supports_async": False,
            "supports_streaming": False
        }
