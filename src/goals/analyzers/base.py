"""Base class for goal analyzers."""

from abc import ABC, abstractmethod
from typing import List

from src.goals._schemas import GoalProposal
from src.goals.constants import DEFAULT_LOOKBACK_HOURS


class BaseAnalyzer(ABC):
    """Abstract base for analyzers that scan execution history."""

    @abstractmethod
    def analyze(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> List[GoalProposal]:
        """Analyze execution history and return goal proposals."""

    @property
    @abstractmethod
    def analyzer_type(self) -> str:
        """Unique identifier for this analyzer type."""
