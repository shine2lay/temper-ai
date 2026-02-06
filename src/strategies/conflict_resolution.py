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

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.strategies.base import AgentOutput, Conflict


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

    def __post_init__(self) -> None:
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
        self.rng = random.Random(seed)  # noqa: S311 — deterministic seed, not crypto

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


# Alias for merit_weighted.py compatibility (ST-01)
ConflictResolver = ConflictResolutionStrategy

# Enhanced types for merit-weighted resolution (M3)


@dataclass
class AgentMerit:
    """Agent merit scores for weighted decision-making.

    Attributes:
        agent_name: Agent identifier
        domain_merit: Success rate in current domain (0-1)
        overall_merit: Global success rate across all domains (0-1)
        recent_performance: Recent task success with time decay (0-1)
        expertise_level: Categorical level (novice, intermediate, expert, etc.)

    Example:
        >>> merit = AgentMerit(
        ...     agent_name="expert_agent",
        ...     domain_merit=0.9,
        ...     overall_merit=0.85,
        ...     recent_performance=0.9,
        ...     expertise_level="expert"
        ... )
        >>> merit.calculate_weight({"domain_merit": 0.4, "overall_merit": 0.3, "recent_performance": 0.3})
        0.883...
    """
    agent_name: str
    domain_merit: float
    overall_merit: float
    recent_performance: float
    expertise_level: str

    def __post_init__(self) -> None:
        """Validate merit scores are in valid range."""
        for score_name in ["domain_merit", "overall_merit", "recent_performance"]:
            score = getattr(self, score_name)
            if not 0 <= score <= 1:
                raise ValueError(
                    f"{score_name} must be between 0 and 1, got {score}"
                )

    def calculate_weight(self, weights: Dict[str, float]) -> float:
        """Calculate composite merit weight.

        Args:
            weights: Weights for each merit component
                - domain_merit: Weight for domain expertise
                - overall_merit: Weight for overall success
                - recent_performance: Weight for recent performance

        Returns:
            Weighted merit score (0-1)

        Example:
            >>> merit = AgentMerit("a", 0.9, 0.8, 0.85, "expert")
            >>> merit.calculate_weight({"domain_merit": 0.5, "overall_merit": 0.3, "recent_performance": 0.2})
            0.865
        """
        domain_weight = weights.get("domain_merit", 0.4)
        overall_weight = weights.get("overall_merit", 0.3)
        recent_weight = weights.get("recent_performance", 0.3)

        return (
            self.domain_merit * domain_weight +
            self.overall_merit * overall_weight +
            self.recent_performance * recent_weight
        )


@dataclass
class ResolutionContext:
    """Context for resolving conflicts with merit-based voting.

    Attributes:
        agent_merits: Merit scores for each agent
        agent_outputs: All agent outputs
        stage_name: Current workflow stage
        workflow_name: Workflow being executed
        workflow_config: Workflow configuration
        previous_resolutions: History of previous conflict resolutions

    Example:
        >>> context = ResolutionContext(
        ...     agent_merits={"agent1": AgentMerit("agent1", 0.9, 0.85, 0.9, "expert")},
        ...     agent_outputs={"agent1": AgentOutput("agent1", "yes", "reason", 0.9, {})},
        ...     stage_name="research",
        ...     workflow_name="mvp",
        ...     workflow_config={},
        ...     previous_resolutions=[]
        ... )
    """
    agent_merits: Dict[str, AgentMerit]
    agent_outputs: Dict[str, AgentOutput]
    stage_name: str
    workflow_name: str
    workflow_config: Dict[str, Any]
    previous_resolutions: List[Any] = field(default_factory=list)


@dataclass
class Resolution:
    """Result of merit-weighted conflict resolution.

    Attributes:
        decision: Resolved decision
        reasoning: Explanation of resolution
        confidence: Confidence in resolution (0-1)
        method: Resolution method used
        winning_agents: Agents who supported the winning decision
        metadata: Additional resolution info

    Example:
        >>> resolution = Resolution(
        ...     decision="Option A",
        ...     reasoning="Expert agent with merit 0.95 chose Option A",
        ...     confidence=0.88,
        ...     method="merit_weighted_auto",
        ...     winning_agents=["expert_agent"],
        ...     metadata={"decision_scores": {"Option A": 0.95}}
        ... )
    """
    decision: Any
    reasoning: str
    confidence: float
    method: str
    winning_agents: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate confidence is in valid range."""
        if not 0 <= self.confidence <= 1:
            raise ValueError(
                f"Confidence must be between 0 and 1, got {self.confidence}"
            )


# Helper functions for merit-weighted voting


def calculate_merit_weighted_votes(
    conflict: Conflict,
    context: ResolutionContext,
    merit_weights: Dict[str, float]
) -> Dict[str, float]:
    """Calculate weighted votes for each decision option.

    Args:
        conflict: Conflict to resolve
        context: Resolution context with agent merits and outputs
        merit_weights: Weights for merit components

    Returns:
        Dict mapping decision to weighted vote score

    Example:
        >>> conflict = Conflict(["a1", "a2"], ["Option A", "Option B"], 0.5, {})
        >>> merit1 = AgentMerit("a1", 0.9, 0.85, 0.9, "expert")
        >>> merit2 = AgentMerit("a2", 0.6, 0.65, 0.6, "novice")
        >>> output1 = AgentOutput("a1", "Option A", "reason", 0.9, {})
        >>> output2 = AgentOutput("a2", "Option B", "reason", 0.8, {})
        >>> context = ResolutionContext(
        ...     agent_merits={"a1": merit1, "a2": merit2},
        ...     agent_outputs={"a1": output1, "a2": output2},
        ...     stage_name="test",
        ...     workflow_name="test",
        ...     workflow_config={},
        ...     previous_resolutions=[]
        ... )
        >>> scores = calculate_merit_weighted_votes(conflict, context, {})
        >>> scores["Option A"] > scores["Option B"]  # Expert has more weight
        True
    """
    decision_scores: Dict[str, float] = {}

    for agent_name in conflict.agents:
        # Get agent's output and merit
        output = context.agent_outputs.get(agent_name)
        if not output:
            continue  # Skip agents without outputs

        merit = context.agent_merits.get(agent_name)
        if not merit:
            # Use default merit (0.5) if not available
            merit_score = 0.5
        else:
            merit_score = merit.calculate_weight(merit_weights)

        # Weighted vote = merit * confidence
        decision = str(output.decision)
        weight = merit_score * output.confidence

        decision_scores[decision] = decision_scores.get(decision, 0.0) + weight

    return decision_scores


def get_highest_weighted_decision(
    decision_scores: Dict[str, float]
) -> tuple[str, float]:
    """Get decision with highest weighted score.

    Args:
        decision_scores: Weighted scores for each decision

    Returns:
        Tuple of (winning_decision, score)

    Raises:
        ValueError: If decision_scores is empty

    Example:
        >>> scores = {"Option A": 1.8, "Option B": 0.9, "Option C": 0.6}
        >>> decision, score = get_highest_weighted_decision(scores)
        >>> decision
        'Option A'
        >>> score
        1.8
    """
    if not decision_scores:
        raise ValueError("No decision scores provided")

    winning_decision = max(decision_scores.items(), key=lambda x: x[1])
    return winning_decision[0], winning_decision[1]
