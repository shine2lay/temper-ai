"""Abstract base class for pattern miners."""

from abc import ABC, abstractmethod
from typing import List

from src.learning.models import LearnedPattern

DEFAULT_LOOKBACK_HOURS = 24


class BaseMiner(ABC):
    """Abstract base for pattern miners.

    Each miner queries observability data over a lookback window
    and returns zero or more discovered patterns.
    """

    @abstractmethod
    def mine(self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> List[LearnedPattern]:
        """Run pattern mining over recent execution data."""

    @property
    @abstractmethod
    def pattern_type(self) -> str:
        """The pattern type string this miner produces."""
