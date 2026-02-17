"""Convergence detection for pattern mining."""

from typing import Any, Dict

from src.learning.store import LearningStore

DEFAULT_WINDOW_SIZE = 10
DEFAULT_CONVERGENCE_THRESHOLD = 0.1
DISPLAY_PRECISION = 4


class ConvergenceDetector:
    """Detects when mining yields diminishing returns."""

    def __init__(
        self,
        store: LearningStore,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> None:
        self.store = store
        self.window_size = window_size

    def is_converged(self, threshold: float = DEFAULT_CONVERGENCE_THRESHOLD) -> bool:
        """Return True if recent mining runs show low novelty."""
        runs = self.store.list_mining_runs(limit=self.window_size)
        if len(runs) < 2:
            return False  # Not enough data
        scores = [r.novelty_score for r in runs]
        avg = sum(scores) / len(scores)
        return avg < threshold

    def get_trend(self) -> Dict[str, Any]:
        """Return novelty trend data for visualization."""
        runs = self.store.list_mining_runs(limit=self.window_size)
        scores = [r.novelty_score for r in runs]
        if not scores:
            return {"scores": [], "moving_average": 0.0, "data_points": 0}
        avg = sum(scores) / len(scores)
        return {
            "scores": scores,
            "moving_average": round(avg, DISPLAY_PRECISION),
            "data_points": len(scores),
        }
