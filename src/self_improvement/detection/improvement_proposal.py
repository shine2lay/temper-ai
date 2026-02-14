"""
Improvement proposal data model for M5 Phase 3.

Represents a single improvement opportunity linking a detected problem
to an applicable improvement strategy.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from src.self_improvement.constants import (
    FIELD_AGENT_NAME,
    FIELD_BASELINE_PROFILE,
    FIELD_CURRENT_PROFILE,
    FIELD_METRICS,
    FIELD_TOTAL_EXECUTIONS,
    FIELD_WINDOW_END,
    FIELD_WINDOW_START,
)
from src.self_improvement.data_models import AgentPerformanceProfile
from src.self_improvement.detection.problem_models import PerformanceProblem

# Priority constants for improvement proposals
PRIORITY_DEFAULT = 2  # Default medium priority
PRIORITY_LOWEST = 3   # Lowest priority level


@dataclass
class ImprovementProposal:
    """
    Represents a single improvement opportunity.

    Links a detected performance problem to an applicable improvement strategy,
    providing all context needed for experiment creation and execution.

    Attributes:
        proposal_id: Unique identifier (UUID)
        agent_name: Name of affected agent
        problem: Detected performance problem
        strategy_name: Name of improvement strategy to apply
        estimated_impact: Expected improvement (0.0-1.0)
        baseline_profile: Historical baseline performance
        current_profile: Current performance
        created_at: When proposal was generated
        priority: Urgency (0=highest, 3=lowest), maps to problem severity
        extra_metadata: Additional context for strategy execution

    Example:
        >>> proposal = ImprovementProposal(
        ...     proposal_id="550e8400-e29b-41d4-a716-446655440000",
        ...     agent_name="product_extractor",
        ...     problem=quality_problem,
        ...     strategy_name="prompt_tuning",
        ...     estimated_impact=0.15,
        ...     baseline_profile=baseline,
        ...     current_profile=current,
        ...     priority=1
        ... )
        >>> print(proposal.get_summary())
        "HIGH priority: prompt_tuning for product_extractor (quality_low, est. +15%)"
    """

    # Identity
    proposal_id: str
    agent_name: str

    # Problem context
    problem: PerformanceProblem

    # Strategy selection
    strategy_name: str
    estimated_impact: float  # 0.0-1.0

    # Performance context (embedded for self-contained proposals)
    baseline_profile: AgentPerformanceProfile
    current_profile: AgentPerformanceProfile

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    priority: int = PRIORITY_DEFAULT  # 0 (highest) to 3 (lowest)
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate proposal attributes."""
        if not (0.0 <= self.estimated_impact <= 1.0):
            raise ValueError(
                f"estimated_impact must be in range [0.0, 1.0], "
                f"got {self.estimated_impact}"
            )
        if self.priority not in (0, 1, 2, PRIORITY_LOWEST):
            raise ValueError(
                f"priority must be 0-{PRIORITY_LOWEST}, got {self.priority}"
            )

    def get_summary(self) -> str:
        """
        Get human-readable proposal summary.

        Returns:
            Formatted summary string

        Example:
            "HIGH priority: prompt_tuning for product_extractor (quality_low, est. +15%)"
        """
        priority_labels = {
            0: "CRITICAL",
            1: "HIGH",
            PRIORITY_DEFAULT: "MEDIUM",
            PRIORITY_LOWEST: "LOW",
        }
        priority_label = priority_labels.get(self.priority, "UNKNOWN")

        return (
            f"{priority_label} priority: {self.strategy_name} for {self.agent_name} "
            f"({self.problem.problem_type.value}, est. +{self.estimated_impact*100:.0f}%)"
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for storage/serialization.

        Returns:
            Dictionary representation

        Example:
            >>> proposal_dict = proposal.to_dict()
            >>> proposal_dict['proposal_id']
            "550e8400-e29b-41d4-a716-446655440000"
        """
        return {
            "proposal_id": self.proposal_id,
            FIELD_AGENT_NAME: self.agent_name,
            "problem": self.problem.to_dict(),
            "strategy_name": self.strategy_name,
            "estimated_impact": self.estimated_impact,
            FIELD_BASELINE_PROFILE: {
                FIELD_AGENT_NAME: self.baseline_profile.agent_name,
                FIELD_WINDOW_START: self.baseline_profile.window_start.isoformat(),
                FIELD_WINDOW_END: self.baseline_profile.window_end.isoformat(),
                FIELD_TOTAL_EXECUTIONS: self.baseline_profile.total_executions,
                FIELD_METRICS: self.baseline_profile.metrics,
            },
            FIELD_CURRENT_PROFILE: {
                FIELD_AGENT_NAME: self.current_profile.agent_name,
                FIELD_WINDOW_START: self.current_profile.window_start.isoformat(),
                FIELD_WINDOW_END: self.current_profile.window_end.isoformat(),
                FIELD_TOTAL_EXECUTIONS: self.current_profile.total_executions,
                FIELD_METRICS: self.current_profile.metrics,
            },
            "created_at": self.created_at.isoformat(),
            "priority": self.priority,
            "extra_metadata": self.extra_metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImprovementProposal":
        """
        Load proposal from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            ImprovementProposal instance

        Example:
            >>> proposal = ImprovementProposal.from_dict(proposal_dict)
        """
        from src.self_improvement.detection.problem_models import PerformanceProblem

        # Reconstruct performance profiles
        baseline_profile = AgentPerformanceProfile(
            agent_name=data[FIELD_BASELINE_PROFILE][FIELD_AGENT_NAME],
            window_start=datetime.fromisoformat(data[FIELD_BASELINE_PROFILE][FIELD_WINDOW_START]),
            window_end=datetime.fromisoformat(data[FIELD_BASELINE_PROFILE][FIELD_WINDOW_END]),
            total_executions=data[FIELD_BASELINE_PROFILE][FIELD_TOTAL_EXECUTIONS],
            metrics=data[FIELD_BASELINE_PROFILE][FIELD_METRICS],
        )

        current_profile = AgentPerformanceProfile(
            agent_name=data[FIELD_CURRENT_PROFILE][FIELD_AGENT_NAME],
            window_start=datetime.fromisoformat(data[FIELD_CURRENT_PROFILE][FIELD_WINDOW_START]),
            window_end=datetime.fromisoformat(data[FIELD_CURRENT_PROFILE][FIELD_WINDOW_END]),
            total_executions=data[FIELD_CURRENT_PROFILE][FIELD_TOTAL_EXECUTIONS],
            metrics=data[FIELD_CURRENT_PROFILE][FIELD_METRICS],
        )

        return cls(
            proposal_id=data["proposal_id"],
            agent_name=data[FIELD_AGENT_NAME],
            problem=PerformanceProblem.from_dict(data["problem"]),
            strategy_name=data["strategy_name"],
            estimated_impact=data["estimated_impact"],
            baseline_profile=baseline_profile,
            current_profile=current_profile,
            created_at=datetime.fromisoformat(data["created_at"]),
            priority=data["priority"],
            extra_metadata=data.get("extra_metadata", {}),
        )

    @staticmethod
    def generate_id() -> str:
        """
        Generate a new proposal ID.

        Returns:
            UUID string

        Example:
            >>> proposal_id = ImprovementProposal.generate_id()
            >>> len(proposal_id)
            36
        """
        return str(uuid.uuid4())
