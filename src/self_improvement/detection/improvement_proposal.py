"""
Improvement proposal data model for M5 Phase 3.

Represents a single improvement opportunity linking a detected problem
to an applicable improvement strategy.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any
import uuid

from src.self_improvement.detection.problem_models import PerformanceProblem
from src.self_improvement.data_models import AgentPerformanceProfile


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
    priority: int = 2  # 0 (highest) to 3 (lowest)
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate proposal attributes."""
        if not (0.0 <= self.estimated_impact <= 1.0):
            raise ValueError(
                f"estimated_impact must be in range [0.0, 1.0], "
                f"got {self.estimated_impact}"
            )
        if self.priority not in (0, 1, 2, 3):
            raise ValueError(
                f"priority must be 0-3, got {self.priority}"
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
            2: "MEDIUM",
            3: "LOW",
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
            "agent_name": self.agent_name,
            "problem": self.problem.to_dict(),
            "strategy_name": self.strategy_name,
            "estimated_impact": self.estimated_impact,
            "baseline_profile": {
                "agent_name": self.baseline_profile.agent_name,
                "window_start": self.baseline_profile.window_start.isoformat(),
                "window_end": self.baseline_profile.window_end.isoformat(),
                "total_executions": self.baseline_profile.total_executions,
                "metrics": self.baseline_profile.metrics,
            },
            "current_profile": {
                "agent_name": self.current_profile.agent_name,
                "window_start": self.current_profile.window_start.isoformat(),
                "window_end": self.current_profile.window_end.isoformat(),
                "total_executions": self.current_profile.total_executions,
                "metrics": self.current_profile.metrics,
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
            agent_name=data["baseline_profile"]["agent_name"],
            window_start=datetime.fromisoformat(data["baseline_profile"]["window_start"]),
            window_end=datetime.fromisoformat(data["baseline_profile"]["window_end"]),
            total_executions=data["baseline_profile"]["total_executions"],
            metrics=data["baseline_profile"]["metrics"],
        )

        current_profile = AgentPerformanceProfile(
            agent_name=data["current_profile"]["agent_name"],
            window_start=datetime.fromisoformat(data["current_profile"]["window_start"]),
            window_end=datetime.fromisoformat(data["current_profile"]["window_end"]),
            total_executions=data["current_profile"]["total_executions"],
            metrics=data["current_profile"]["metrics"],
        )

        return cls(
            proposal_id=data["proposal_id"],
            agent_name=data["agent_name"],
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
