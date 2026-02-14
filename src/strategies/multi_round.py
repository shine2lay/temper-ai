"""Unified multi-round agent communication strategy.

Supports three interaction modes:
- "dialogue": Collaborative. Agents build on each other's insights.
- "debate": Adversarial. Agents challenge positions and defend stances.
- "consensus": Single-round majority vote (no re-invocation).

Replaces the separate DialogueOrchestrator and DebateAndSynthesize classes
with a single configurable strategy.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.strategies._dialogue_helpers import (
    calculate_exact_match_convergence,
    calculate_semantic_similarity,
    curate_recent,
    curate_relevant,
    merit_weighted_synthesis,
)
from src.strategies.base import AgentOutput, CollaborationStrategy, SynthesisResult
from src.strategies.constants import (
    DEFAULT_CONTEXT_WINDOW_SIZE,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MIN_ROUNDS,
)

logger = logging.getLogger(__name__)

# Valid interaction modes
VALID_MODES = frozenset({"dialogue", "debate", "consensus"})
VALID_CONTEXT_STRATEGIES = frozenset({"full", "recent", "relevant"})

# --- Stance extraction ---
VALID_STANCES = frozenset({"AGREE", "DISAGREE", "PARTIAL"})
_STANCE_BRACKET = re.compile(r"\[STANCE:\s*(AGREE|DISAGREE|PARTIAL)\]", re.IGNORECASE)
_STANCE_LOOSE = re.compile(r"STANCE[*:\s]+(AGREE|DISAGREE|PARTIAL)", re.IGNORECASE)
_STANCE_COMPARE_PROMPT = (
    "You are classifying an agent's stance relative to other agents in a debate.\n\n"
    "Other agents said:\n{others}\n\n"
    "This agent said:\n{output}\n\n"
    "Does this agent AGREE, DISAGREE, or PARTIALLY agree with the others?\n"
    "Reply with exactly one word: AGREE, DISAGREE, or PARTIAL."
)
_STANCE_PER_AGENT_TRUNCATE = 500  # scanner: skip-magic
_STANCE_OUTPUT_TRUNCATE = 1000  # scanner: skip-magic


def _extract_stance_regex(text: str) -> str:
    """Fast-path: extract stance tag from agent output via regex."""
    if not text:
        return ""
    match = _STANCE_BRACKET.search(text)
    if match:
        return match.group(1).upper()
    match = _STANCE_LOOSE.search(text)
    if match:
        return match.group(1).upper()
    return ""


def _extract_stance_via_llm(
    llm_provider: Any,
    output_text: str,
    other_outputs: List[tuple],
) -> str:
    """Use a short LLM call to classify agent stance by comparing to others.

    Args:
        llm_provider: LLM provider with .complete(prompt, **kwargs) method
        output_text: This agent's full response text
        other_outputs: List of (agent_name, output_text) for other agents

    Returns:
        Uppercase stance ('AGREE', 'DISAGREE', 'PARTIAL') or empty string.
    """
    if not output_text or not llm_provider or not other_outputs:
        return ""

    others_summary = "\n".join(
        f"- {name}: {text[:_STANCE_PER_AGENT_TRUNCATE]}"
        for name, text in other_outputs
        if text
    )
    if not others_summary:
        return ""

    prompt = _STANCE_COMPARE_PROMPT.format(
        others=others_summary,
        output=output_text[:_STANCE_OUTPUT_TRUNCATE],
    )

    try:
        response = llm_provider.complete(prompt, max_tokens=10, temperature=0.0)
        if response and response.content:
            word = response.content.strip().upper().split()[0]
            word = re.sub(r"[^A-Z]", "", word)
            if word in VALID_STANCES:
                return word
    except Exception:
        logger.debug("Stance extraction LLM call failed", exc_info=True)

    return ""


# Mode-specific defaults (applied when param is None)
_MODE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "dialogue": {
        "convergence_threshold": 0.85,
        "max_rounds": DEFAULT_MAX_ROUNDS,
        "min_rounds": DEFAULT_MIN_ROUNDS,
    },
    "debate": {
        "convergence_threshold": 0.80,
        "max_rounds": DEFAULT_MAX_ROUNDS,
        "min_rounds": DEFAULT_MIN_ROUNDS,
    },
    "consensus": {
        "convergence_threshold": 1.0,
        "max_rounds": 1,
        "min_rounds": 1,
    },
}


@dataclass
class CommunicationRound:
    """Single round of multi-agent communication.

    Attributes:
        round_number: Round index (0-based)
        agent_outputs: Outputs from all agents this round
        convergence_score: Agreement level (0-1)
        metadata: Additional round metadata
    """
    round_number: int
    agent_outputs: List[AgentOutput]
    convergence_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommunicationHistory:
    """Complete communication transcript across all rounds.

    Attributes:
        rounds: All communication rounds
        total_rounds: Number of rounds executed
        converged: Whether communication converged
        convergence_round: Round where convergence occurred (-1 if not converged)
        early_stop_reason: Reason for stopping early
        total_cost_usd: Accumulated cost
    """
    rounds: List[CommunicationRound] = field(default_factory=list)
    total_rounds: int = 0
    converged: bool = False
    convergence_round: int = -1
    early_stop_reason: Optional[str] = None
    total_cost_usd: float = 0.0


class MultiRoundStrategy(CollaborationStrategy):
    """Unified multi-round agent communication strategy.

    Modes:
    - "dialogue": Collaborative. Agents build on each other's insights.
    - "debate": Adversarial. Agents challenge positions and defend stances.
    - "consensus": Single-round majority vote (no re-invocation).

    Example:
        >>> strategy = MultiRoundStrategy(mode="debate", max_rounds=3)
        >>> strategy.requires_requery
        True
        >>> strategy.get_round_context(1, "skeptic")
        {'interaction_mode': 'debate', 'mode_instruction': '...', ...}
    """

    # Class-level singleton for SentenceTransformer model
    _embedding_model: Any = None
    _embedding_model_loaded: bool = False

    def __init__(
        self,
        mode: str = "dialogue",
        max_rounds: Optional[int] = None,
        min_rounds: Optional[int] = None,
        convergence_threshold: Optional[float] = None,
        use_semantic_convergence: bool = True,
        context_strategy: str = "full",
        context_window_size: int = DEFAULT_CONTEXT_WINDOW_SIZE,
        cost_budget_usd: Optional[float] = None,
        use_merit_weighting: bool = False,
        merit_domain: Optional[str] = None,
        require_unanimous: bool = False,
    ):
        """Initialize multi-round strategy.

        Args:
            mode: Interaction mode ("dialogue", "debate", or "consensus")
            max_rounds: Maximum rounds (None = use mode default)
            min_rounds: Minimum rounds before convergence check (None = use mode default)
            convergence_threshold: Convergence threshold 0-1 (None = use mode default)
            use_semantic_convergence: Use semantic similarity for convergence
            context_strategy: History propagation ("full", "recent", "relevant")
            context_window_size: For "recent" strategy, how many rounds
            cost_budget_usd: Max cost in USD, None for unlimited
            use_merit_weighting: Weight opinions by historical performance
            merit_domain: Domain for merit score lookup
            require_unanimous: Require 100% agreement

        Raises:
            ValueError: If parameters are invalid
        """
        if mode not in VALID_MODES:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(VALID_MODES))}"
            )
        if context_strategy not in VALID_CONTEXT_STRATEGIES:
            raise ValueError(
                f"Invalid context_strategy '{context_strategy}'. "
                f"Must be one of: {', '.join(sorted(VALID_CONTEXT_STRATEGIES))}"
            )

        self.mode = mode
        defaults = _MODE_DEFAULTS[mode]

        self.max_rounds = max_rounds if max_rounds is not None else defaults["max_rounds"]
        self.min_rounds = min_rounds if min_rounds is not None else defaults["min_rounds"]
        self.convergence_threshold = (
            convergence_threshold if convergence_threshold is not None
            else defaults["convergence_threshold"]
        )

        if self.max_rounds < 1:
            raise ValueError(f"max_rounds must be >= 1, got {self.max_rounds}")
        if self.min_rounds < 1:
            raise ValueError(f"min_rounds must be >= 1, got {self.min_rounds}")
        if not 0 <= self.convergence_threshold <= 1:
            raise ValueError(
                f"convergence_threshold must be in [0, 1], got {self.convergence_threshold}"
            )
        if cost_budget_usd is not None and cost_budget_usd <= 0:
            raise ValueError(f"cost_budget_usd must be > 0, got {cost_budget_usd}")
        if context_window_size < 1:
            raise ValueError(f"context_window_size must be >= 1, got {context_window_size}")

        self.use_semantic_convergence = use_semantic_convergence
        self.context_strategy = context_strategy
        self.context_window_size = context_window_size
        self.cost_budget_usd = cost_budget_usd
        self.use_merit_weighting = use_merit_weighting
        self.merit_domain = merit_domain
        self.require_unanimous = require_unanimous
        self._embeddings_available: Optional[bool] = None

    @property
    def requires_requery(self) -> bool:
        """Signal to executor: multi-round modes need agent re-invocation."""
        return self.mode != "consensus"

    def get_round_context(self, round_number: int, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """Get mode-specific context injected into agent input_data.

        Returns keys that will be merged into the agent's input_data dict,
        giving agents awareness of the interaction mode and round context.

        Args:
            round_number: Current round number (0-based)
            agent_name: Name of the agent receiving context

        Returns:
            Dict with keys: interaction_mode, mode_instruction, debate_framing, round_number
        """
        context: Dict[str, Any] = {
            "interaction_mode": self.mode,
            "round_number": round_number,
        }

        if self.mode == "debate":
            context["mode_instruction"] = (
                "You are in a structured DEBATE. Challenge other agents' positions, "
                "defend your own stance with evidence, and identify weaknesses in "
                "opposing arguments. Be adversarial but constructive."
            )
            if round_number == 0:
                context["debate_framing"] = "State your initial position clearly with supporting arguments."
            else:
                context["debate_framing"] = (
                    "Review other agents' arguments from previous rounds. "
                    "Rebut weak points, strengthen your position, or concede if convinced."
                )
        elif self.mode == "dialogue":
            context["mode_instruction"] = (
                "You are in a collaborative DIALOGUE. Build on other agents' insights, "
                "find common ground, and work toward a shared understanding. "
                "Be constructive and integrative."
            )
            if round_number == 0:
                context["debate_framing"] = "Share your initial perspective and key insights."
            else:
                context["debate_framing"] = (
                    "Consider what other agents have shared. "
                    "Build on their insights, identify areas of agreement, "
                    "and refine the collective understanding."
                )
        else:  # consensus
            context["mode_instruction"] = (
                "Provide your independent assessment. This is a single-round vote."
            )
            context["debate_framing"] = "State your position clearly."

        return context

    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any],
    ) -> SynthesisResult:
        """Synthesize agent outputs into a unified decision.

        For consensus mode: uses majority vote or merit-weighted synthesis.
        For debate/dialogue: synthesizes final-round outputs.

        Args:
            agent_outputs: Agent outputs (from final round for multi-round)
            config: Additional configuration

        Returns:
            SynthesisResult with synthesized decision
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

        result.metadata["strategy"] = f"multi_round_{self.mode}"
        result.metadata["mode"] = self.mode
        return result

    def curate_dialogue_history(
        self,
        dialogue_history: List[Dict[str, Any]],
        current_round: int,
        agent_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Curate dialogue history based on context strategy.

        Args:
            dialogue_history: Full dialogue history
            current_round: Current round number
            agent_name: Name of agent receiving the history

        Returns:
            Curated dialogue history
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
            logger.warning("Unknown context_strategy '%s', using 'full'", self.context_strategy)
            return dialogue_history

    def calculate_convergence(
        self,
        current_outputs: List[AgentOutput],
        previous_outputs: List[AgentOutput],
    ) -> float:
        """Calculate convergence score between rounds.

        Args:
            current_outputs: Current round outputs
            previous_outputs: Previous round outputs

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
                        "Semantic similarity failed: %s. Falling back to exact match.", e
                    )

        return calculate_exact_match_convergence(current_outputs, previous_outputs)

    def extract_stances(
        self,
        outputs: List[AgentOutput],
        llm_providers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Extract stance (AGREE/DISAGREE/PARTIAL) from each agent's output.

        Uses regex fast-path first, then falls back to an LLM classification
        call that compares this agent's output against the other agents.

        Args:
            outputs: Agent outputs from a single round
            llm_providers: Mapping of agent_name -> LLM provider for fallback

        Returns:
            Dict mapping agent_name -> stance string (or empty if undetected)
        """
        stances: Dict[str, str] = {}
        providers = llm_providers or {}
        unresolved: List[AgentOutput] = []

        # Pass 1: try regex (free)
        for output in outputs:
            stance = _extract_stance_regex(output.decision or "")
            if stance:
                stances[output.agent_name] = stance
            else:
                unresolved.append(output)

        # Pass 2: LLM classification with comparison context
        for output in unresolved:
            other_outputs = [
                (o.agent_name, o.decision or "")
                for o in outputs
                if o.agent_name != output.agent_name
            ]
            llm = providers.get(output.agent_name)
            stance = _extract_stance_via_llm(llm, output.decision or "", other_outputs)
            stances[output.agent_name] = stance

        return stances

    def _check_embeddings_available(self) -> bool:
        """Check if sentence-transformers is available."""
        if self._embeddings_available is not None:
            return self._embeddings_available
        try:
            import sentence_transformers  # type: ignore[import-not-found, unused-ignore]  # noqa: F401
            self._embeddings_available = True
            return True
        except ImportError:
            self._embeddings_available = False
            logger.warning(
                "sentence-transformers not available, using exact match convergence."
            )
            return False

    @classmethod
    def _get_embedding_model(cls) -> Any:
        """Get or lazily load the class-level SentenceTransformer model."""
        if not cls._embedding_model_loaded:
            try:
                from sentence_transformers import (
                    SentenceTransformer,  # type: ignore[import-not-found, unused-ignore]
                )
                cls._embedding_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
                cls._embedding_model_loaded = True
            except (ImportError, OSError, RuntimeError) as e:
                logger.warning("Failed to load embedding model: %s", e)
        return cls._embedding_model

    def get_capabilities(self) -> Dict[str, bool]:
        """Get strategy capabilities."""
        return {
            "supports_debate": self.mode == "debate",
            "supports_dialogue": self.mode == "dialogue",
            "supports_convergence": self.mode != "consensus",
            "supports_merit_weighting": self.use_merit_weighting,
            "supports_partial_participation": True,
            "supports_async": False,
            "supports_multi_round": self.mode != "consensus",
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Get strategy metadata."""
        return {
            **super().get_metadata(),
            "config_schema": {
                "mode": {"type": "str", "default": "dialogue", "options": list(VALID_MODES)},
                "max_rounds": {"type": "int", "default": "mode-dependent"},
                "min_rounds": {"type": "int", "default": 1},
                "convergence_threshold": {"type": "float", "default": "mode-dependent"},
                "context_strategy": {"type": "str", "default": "full", "options": list(VALID_CONTEXT_STRATEGIES)},
                "use_merit_weighting": {"type": "bool", "default": False},
                "require_unanimous": {"type": "bool", "default": False},
            },
        }
