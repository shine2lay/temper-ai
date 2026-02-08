"""Abstract base classes and types for multi-agent collaboration strategies.

This module defines the core interfaces for synthesizing outputs from multiple
agents into unified decisions. It provides:
- CollaborationStrategy ABC: Base class for all collaboration strategies
- AgentOutput: Standardized format for agent results
- SynthesisResult: Output format for synthesized decisions
- Conflict: Representation of agent disagreements
- Utility functions for common synthesis operations

Design Philosophy:
- Strategy pattern enables experimentation with collaboration approaches
- Feature detection via get_capabilities() enables runtime capability checking
- Observability first: track conflicts, votes, reasoning for debugging
- Type-safe: Full type hints and validation for all data structures

Example:
    >>> class SimpleConsensus(CollaborationStrategy):
    ...     def synthesize(self, agent_outputs, config):
    ...         decision = extract_majority_decision(agent_outputs)
    ...         confidence = calculate_consensus_confidence(agent_outputs, decision)
    ...         return SynthesisResult(
    ...             decision=decision,
    ...             confidence=confidence,
    ...             method="consensus",
    ...             votes={},
    ...             conflicts=[],
    ...             reasoning="Majority vote",
    ...             metadata={}
    ...         )
    ...     def get_capabilities(self):
    ...         return {"supports_debate": False}
"""

import json
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.constants.probabilities import PROB_LOW_MEDIUM

# Constants
DEFAULT_MOST_COMMON_LIMIT = 4  # Number of items to retrieve from Counter.most_common()


class SynthesisMethod(Enum):
    """Methods for combining agent outputs.

    Attributes:
        CONSENSUS: Simple majority voting
        WEIGHTED_MERGE: Weighted by agent confidence or merit
        BEST_OF: Select single best output
        DEBATE_EXTRACT: Extract decision from multi-round debate
        HIERARCHICAL: Lead agent with advisor review
    """
    CONSENSUS = "consensus"
    WEIGHTED_MERGE = "weighted_merge"
    BEST_OF = "best_of"
    DEBATE_EXTRACT = "debate_extract"
    HIERARCHICAL = "hierarchical"


@dataclass
class AgentOutput:
    """Standardized agent output format.

    This dataclass standardizes how agent results are represented for
    synthesis. All agents participating in collaboration must return
    outputs in this format.

    Attributes:
        agent_name: Unique identifier for the agent
        decision: Agent's primary decision/output (can be any type)
        reasoning: Agent's explanation for the decision
        confidence: Agent's confidence score (0.0 to 1.0)
        metadata: Additional information (tokens used, cost, duration, etc.)

    Example:
        >>> output = AgentOutput(
        ...     agent_name="researcher_1",
        ...     decision="Option A is best",
        ...     reasoning="Based on analysis of X, Y, Z...",
        ...     confidence=0.85,
        ...     metadata={"tokens": 1500, "duration_seconds": 3.2}
        ... )
    """
    agent_name: str
    decision: Any
    reasoning: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate confidence score is in valid range."""
        if not 0 <= self.confidence <= 1:
            raise ValueError(
                f"Confidence must be between 0 and 1, got {self.confidence}"
            )
        if not self.agent_name:
            raise ValueError("agent_name cannot be empty")


@dataclass
class Conflict:
    """Represents disagreement between agents.

    Conflicts are detected when agents propose different decisions or
    when the disagreement score exceeds a threshold.

    Attributes:
        agents: List of agent names involved in conflict
        decisions: List of conflicting decisions
        disagreement_score: Severity of disagreement (0.0 = minor, 1.0 = severe)
        context: Additional context about the conflict

    Example:
        >>> conflict = Conflict(
        ...     agents=["agent1", "agent2", "agent3"],
        ...     decisions=["Option A", "Option B"],
        ...     disagreement_score=0.67,
        ...     context={"num_rounds": 3, "resolved": False}
        ... )
    """
    agents: List[str]
    decisions: List[Any]
    disagreement_score: float
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate conflict data."""
        if not 0 <= self.disagreement_score <= 1:
            raise ValueError(
                f"disagreement_score must be between 0 and 1, "
                f"got {self.disagreement_score}"
            )
        if not self.agents:
            raise ValueError("Conflict must have at least one agent")
        if not self.decisions:
            raise ValueError("Conflict must have at least one decision")


@dataclass
class SynthesisResult:
    """Result of synthesizing multiple agent outputs.

    This dataclass represents the final output after combining multiple
    agent decisions into a unified result.

    Attributes:
        decision: Final synthesized decision
        confidence: Confidence in the synthesis (0.0 to 1.0)
        method: Name of synthesis method used
        votes: Vote counts per decision option
        conflicts: List of conflicts detected during synthesis
        reasoning: Explanation of how the decision was reached
        metadata: Additional info (rounds, convergence, participation, etc.)

    Example:
        >>> result = SynthesisResult(
        ...     decision="Option A",
        ...     confidence=0.85,
        ...     method="consensus",
        ...     votes={"Option A": 3, "Option B": 1},
        ...     conflicts=[],
        ...     reasoning="3 out of 4 agents voted for Option A",
        ...     metadata={"num_rounds": 1, "participation": 4}
        ... )
    """
    decision: Any
    confidence: float
    method: str
    votes: Dict[str, int]
    conflicts: List[Conflict]
    reasoning: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate confidence score is in valid range."""
        if not 0 <= self.confidence <= 1:
            raise ValueError(
                f"Confidence must be between 0 and 1, got {self.confidence}"
            )


class CollaborationStrategy(ABC):
    """Abstract base class for multi-agent collaboration strategies.

    Collaboration strategies define how multiple agents' outputs are
    synthesized into a unified decision. Different strategies implement
    different collaboration patterns:
    - Consensus: Simple majority voting
    - Debate: Multi-round argumentation with convergence
    - Merit-weighted: Weight votes by agent merit scores
    - Hierarchical: Lead agent decides with advisor review

    Subclasses must implement:
    - synthesize(): Core synthesis logic
    - get_capabilities(): Feature detection

    Example:
        >>> class MyStrategy(CollaborationStrategy):
        ...     def synthesize(self, agent_outputs, config):
        ...         # Custom synthesis logic
        ...         return SynthesisResult(...)
        ...     def get_capabilities(self):
        ...         return {"supports_debate": True}
        >>>
        >>> strategy = MyStrategy()
        >>> outputs = [AgentOutput(...), AgentOutput(...)]
        >>> result = strategy.synthesize(outputs, {})
    """

    @abstractmethod
    def synthesize(
        self,
        agent_outputs: List[AgentOutput],
        config: Dict[str, Any]
    ) -> SynthesisResult:
        """Synthesize multiple agent outputs into unified decision.

        This is the core method that implements the collaboration strategy.
        It takes agent outputs and produces a single synthesized result.

        Args:
            agent_outputs: List of outputs from all participating agents
            config: Strategy-specific configuration parameters

        Returns:
            SynthesisResult containing the synthesized decision, confidence,
            votes, conflicts, and reasoning

        Raises:
            ValueError: If agent_outputs is empty or invalid
            RuntimeError: If synthesis fails due to irreconcilable conflicts

        Example:
            >>> outputs = [
            ...     AgentOutput("agent1", "yes", "reason1", 0.9, {}),
            ...     AgentOutput("agent2", "yes", "reason2", 0.8, {})
            ... ]
            >>> result = strategy.synthesize(outputs, {"threshold": 0.5})
            >>> result.decision
            'yes'
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, bool]:
        """Get strategy capabilities for feature detection.

        Returns a dictionary of boolean flags indicating which features
        this strategy supports. This enables runtime capability checking
        and graceful degradation.

        Returns:
            Dict of capability flags:
            - supports_debate: Multi-round debate/argumentation
            - supports_convergence: Convergence detection
            - supports_merit_weighting: Uses agent merit scores
            - supports_partial_participation: Can handle missing agents
            - supports_async: Can run asynchronously
            - supports_streaming: Can yield intermediate results

        Example:
            >>> caps = strategy.get_capabilities()
            >>> if caps.get("supports_debate"):
            ...     # Run multi-round debate
            ... else:
            ...     # Fall back to single-round voting
        """
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """Get strategy metadata for introspection.

        Returns basic information about the strategy including name,
        version, description, and expected config schema.

        Returns:
            Strategy metadata dict with keys:
            - name: Strategy class name
            - version: Strategy version string
            - description: Brief description from docstring
            - config_schema: Expected configuration format

        Example:
            >>> metadata = strategy.get_metadata()
            >>> print(metadata["name"])
            'ConsensusStrategy'
        """
        return {
            "name": self.__class__.__name__,
            "version": "1.0",
            "description": self.__doc__ or "",
            "config_schema": {}
        }

    @property
    def requires_requery(self) -> bool:
        """Whether this strategy requires re-invoking agents.

        Multi-round strategies (e.g., dialogue orchestrator) need to re-invoke
        agents across multiple rounds with accumulated context. One-shot strategies
        (e.g., consensus, existing debate) operate on pre-collected outputs.

        Returns:
            True: Multi-round strategies requiring agent re-invocation
            False: One-shot strategies (default for backward compatibility)

        Default: False

        Example:
            >>> consensus = ConsensusStrategy()
            >>> consensus.requires_requery
            False
            >>> dialogue = DialogueOrchestrator()
            >>> dialogue.requires_requery
            True
        """
        return False

    def validate_inputs(self, agent_outputs: List[AgentOutput]) -> None:
        """Validate agent outputs before synthesis.

        Performs common validation checks on agent outputs to ensure
        they are in the correct format and contain valid data.

        Args:
            agent_outputs: Outputs to validate

        Raises:
            ValueError: If validation fails (empty list, wrong types,
                       duplicate agent names, invalid confidence scores)

        Example:
            >>> strategy.validate_inputs(outputs)  # Raises if invalid
        """
        if not agent_outputs:
            raise ValueError("agent_outputs cannot be empty")

        if not all(isinstance(o, AgentOutput) for o in agent_outputs):
            raise ValueError("All outputs must be AgentOutput instances")

        # Check for duplicate agent names
        agent_names = [o.agent_name for o in agent_outputs]
        if len(agent_names) != len(set(agent_names)):
            from collections import Counter
            counts = Counter(agent_names)
            duplicates = {name: count for name, count in counts.items() if count > 1}
            raise ValueError(f"Duplicate agent names detected: {duplicates}")

    def detect_conflicts(
        self,
        agent_outputs: List[AgentOutput],
        threshold: float = PROB_LOW_MEDIUM
    ) -> List[Conflict]:
        """Detect conflicts between agent decisions.

        Analyzes agent outputs to identify disagreements. A conflict is
        detected when agents propose different decisions and the disagreement
        score exceeds the threshold.

        Args:
            agent_outputs: Outputs to check for conflicts
            threshold: Disagreement threshold (0.0 to 1.0). Conflicts with
                      disagreement_score below this are ignored.

        Returns:
            List of detected conflicts, sorted by severity (highest first)

        Example:
            >>> conflicts = strategy.detect_conflicts(outputs, threshold=0.3)
            >>> if conflicts:
            ...     print(f"Found {len(conflicts)} conflicts")
            ...     print(f"Severity: {conflicts[0].disagreement_score}")
        """
        conflicts = []

        # Group outputs by decision (use actual decision values, not strings)
        decision_groups: Dict[Any, List[AgentOutput]] = {}
        for output in agent_outputs:
            # ST-05: Decisions may be unhashable types (dict, list). Use the
            # decision directly when hashable; fall back to its JSON repr for
            # unhashable types so they can serve as dict keys.
            key = output.decision
            try:
                hash(key)
            except TypeError:
                key = json.dumps(key, sort_keys=True, default=str)
            if key not in decision_groups:
                decision_groups[key] = []
            decision_groups[key].append(output)

        # If more than one decision group, we have disagreement
        if len(decision_groups) > 1:
            # Calculate disagreement score:
            # 1.0 - (largest_group_size / total_agents)
            largest_group = max(len(g) for g in decision_groups.values())
            disagreement_score = 1.0 - (largest_group / len(agent_outputs))

            # Only report if above threshold
            if disagreement_score >= threshold:
                conflicts.append(Conflict(
                    agents=[o.agent_name for o in agent_outputs],
                    decisions=list(decision_groups.keys()),
                    disagreement_score=round(disagreement_score, 4),  # Explicit rounding for consistency  # noqa: Standard precision
                    context={
                        "num_decisions": len(decision_groups),
                        "largest_group_size": largest_group,
                        "decision_distribution": {
                            str(k): len(v) for k, v in decision_groups.items()
                        }
                    }
                ))

        # Sort by severity (highest first)
        conflicts.sort(key=lambda c: c.disagreement_score, reverse=True)

        return conflicts


# Utility functions for common synthesis operations

def calculate_consensus_confidence(
    agent_outputs: List[AgentOutput],
    decision: Any
) -> float:
    """Calculate confidence based on consensus strength.

    Combines two factors:
    1. Consensus strength: percentage of agents supporting the decision
    2. Average confidence: mean confidence of supporting agents

    Args:
        agent_outputs: All agent outputs
        decision: The consensus decision to calculate confidence for

    Returns:
        Combined confidence score (0.0 to 1.0)

    Example:
        >>> outputs = [
        ...     AgentOutput("a1", "yes", "r1", 0.9, {}),
        ...     AgentOutput("a2", "yes", "r2", 0.8, {}),
        ...     AgentOutput("a3", "no", "r3", 0.7, {})
        ... ]
        >>> confidence = calculate_consensus_confidence(outputs, "yes")
        >>> # 2/3 agents * avg(0.9, 0.8) = 0.667 * 0.85 = 0.567
        >>> round(confidence, 2)
        0.57
    """
    # Get agents supporting this decision
    supporters = [o for o in agent_outputs if o.decision == decision]

    if not supporters:
        return 0.0

    # Consensus strength: percentage of agents
    consensus_strength = len(supporters) / len(agent_outputs)

    # Average confidence of supporters
    avg_confidence = sum(o.confidence for o in supporters) / len(supporters)

    # Combined confidence (multiply both factors)
    return consensus_strength * avg_confidence


def extract_majority_decision(agent_outputs: List[AgentOutput]) -> Optional[Any]:
    """Extract majority decision from agent outputs.

    Finds the decision that was chosen by the most agents. Returns None
    if there is a tie (no clear majority).

    Args:
        agent_outputs: All agent outputs

    Returns:
        Most common decision, or None if there's a tie

    Example:
        >>> outputs = [
        ...     AgentOutput("a1", "yes", "r1", 0.9, {}),
        ...     AgentOutput("a2", "yes", "r2", 0.8, {}),
        ...     AgentOutput("a3", "no", "r3", 0.7, {})
        ... ]
        >>> extract_majority_decision(outputs)
        'yes'
        >>>
        >>> # Tie case
        >>> outputs.append(AgentOutput("a4", "no", "r4", 0.8, {}))
        >>> extract_majority_decision(outputs)  # Returns None (tie)
    """
    if not agent_outputs:
        return None

    # Count decisions
    decisions = [o.decision for o in agent_outputs]
    counts = Counter(decisions)

    if not counts:
        return None

    # Get most common (up to DEFAULT_MOST_COMMON_LIMIT to check for ties)
    most_common = counts.most_common(2)

    # Check for tie
    if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
        return None  # Tie, needs tiebreaker

    return most_common[0][0]


def calculate_vote_distribution(
    agent_outputs: List[AgentOutput]
) -> Dict[Any, int]:
    """Calculate vote distribution across all decisions.

    Note: Returns decision values in their original types (not converted to strings).
    For mixed decision types, use str() on keys if string representation needed.

    Args:
        agent_outputs: All agent outputs

    Returns:
        Dict mapping decision to vote count (preserves decision types)

    Example:
        >>> outputs = [
        ...     AgentOutput("a1", "yes", "r1", 0.9, {}),
        ...     AgentOutput("a2", "yes", "r2", 0.8, {}),
        ...     AgentOutput("a3", "no", "r3", 0.7, {})
        ... ]
        >>> calculate_vote_distribution(outputs)
        {'yes': 2, 'no': 1}
    """
    decisions = [o.decision for o in agent_outputs]
    return dict(Counter(decisions))
