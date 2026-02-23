"""Multi-agent collaboration strategies for Temper AI.

This package provides abstract interfaces and concrete implementations for
synthesizing outputs from multiple agents into unified decisions.

Available strategies:
- ConsensusStrategy: Simple majority voting
- ConcatenateStrategy: Join independent parallel outputs
- DebateStrategy: Multi-round argumentation
- MeritWeightedStrategy: Weight votes by agent merit scores
- HierarchicalStrategy: Lead agent with advisor review

Conflict resolution strategies:
- HighestConfidenceResolver: Pick agent with highest confidence
- RandomTiebreakerResolver: Random selection for tiebreaking
- MeritWeightedResolver: Weight by agent merit scores

Example:
    >>> from temper_ai.agent.strategies.base import AgentOutput
    >>> from temper_ai.agent.strategies.consensus import ConsensusStrategy
    >>>
    >>> outputs = [
    ...     AgentOutput("agent1", "Option A", "reasoning", 0.9, {}),
    ...     AgentOutput("agent2", "Option A", "reasoning", 0.8, {})
    ... ]
    >>> strategy = ConsensusStrategy()
    >>> result = strategy.synthesize(outputs, {})
    >>> print(result.decision)
    'Option A'
"""

from temper_ai.agent.strategies.base import (
    AgentOutput,
    CollaborationStrategy,
    Conflict,
    SynthesisMethod,
    SynthesisResult,
    calculate_consensus_confidence,
    calculate_vote_distribution,
    extract_majority_decision,
)
from temper_ai.agent.strategies.conflict_resolution import (
    ConflictResolutionStrategy,
    HighestConfidenceResolver,
    MeritWeightedResolver,
    RandomTiebreakerResolver,
    ResolutionMethod,
    ResolutionResult,
    create_resolver,
)

__all__ = [
    # Base collaboration classes
    "CollaborationStrategy",
    "AgentOutput",
    "SynthesisResult",
    "Conflict",
    "SynthesisMethod",
    "calculate_consensus_confidence",
    "extract_majority_decision",
    "calculate_vote_distribution",
    # Conflict resolution classes
    "ConflictResolutionStrategy",
    "ResolutionResult",
    "ResolutionMethod",
    "HighestConfidenceResolver",
    "RandomTiebreakerResolver",
    "MeritWeightedResolver",
    "create_resolver",
]

__version__ = "1.0.0"
