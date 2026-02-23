"""Data service for learning dashboard page."""

from typing import Any

from temper_ai.learning.convergence import ConvergenceDetector
from temper_ai.learning.store import LearningStore

DEFAULT_PATTERN_LIMIT = 50
DEFAULT_RUN_LIMIT = 20


class LearningDataService:
    """Provides data for learning dashboard endpoints."""

    def __init__(self, store: LearningStore) -> None:
        self.store = store
        self._convergence = ConvergenceDetector(store)

    def get_pattern_summary(self) -> dict[str, Any]:
        """Get pattern counts by type and top patterns."""
        patterns = self.store.list_patterns(status=None, limit=DEFAULT_PATTERN_LIMIT)
        by_type: dict[str, int] = {}
        for p in patterns:
            by_type[p.pattern_type] = by_type.get(p.pattern_type, 0) + 1

        top = [
            {
                "id": p.id,
                "type": p.pattern_type,
                "title": p.title,
                "confidence": p.confidence,
                "impact": p.impact_score,
            }
            for p in patterns[:10]
        ]
        return {"counts_by_type": by_type, "total": len(patterns), "top_patterns": top}

    def get_mining_history(self) -> list[dict[str, Any]]:
        """Get recent mining runs for display."""
        runs = self.store.list_mining_runs(limit=DEFAULT_RUN_LIMIT)
        return [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "status": r.status,
                "patterns_found": r.patterns_found,
                "patterns_new": r.patterns_new,
                "novelty_score": r.novelty_score,
            }
            for r in runs
        ]

    def get_convergence_data(self) -> dict[str, Any]:
        """Get convergence trend data for charting."""
        trend = self._convergence.get_trend()
        trend["converged"] = self._convergence.is_converged()
        return trend

    def get_recommendations(self) -> list[dict[str, Any]]:
        """Get pending recommendations."""
        recs = self.store.list_recommendations(status="pending")
        return [
            {
                "id": r.id,
                "pattern_id": r.pattern_id,
                "field_path": r.field_path,
                "current_value": r.current_value,
                "recommended_value": r.recommended_value,
                "rationale": r.rationale,
            }
            for r in recs
        ]
