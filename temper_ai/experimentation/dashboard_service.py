"""Data service for experimentation dashboard endpoints."""

from typing import Any

DEFAULT_EXPERIMENT_LIMIT = 50


class ExperimentDataService:
    """Provides data for experimentation dashboard endpoints.

    Wraps ExperimentService to convert model objects to JSON-serializable dicts.
    """

    def __init__(self) -> None:
        from temper_ai.experimentation.service import ExperimentService

        self._service = ExperimentService()
        self._service.initialize()

    def list_experiments(
        self,
        status: str | None = None,
        limit: int = DEFAULT_EXPERIMENT_LIMIT,
    ) -> list[dict[str, Any]]:
        """List experiments, optionally filtered by status."""
        from temper_ai.experimentation.models import ExperimentStatus

        status_enum = ExperimentStatus(status) if status else None
        experiments = self._service.list_experiments(status=status_enum)
        results = [_experiment_to_dict(exp) for exp in experiments[:limit]]
        return results

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        """Get a single experiment by ID."""
        exp = self._service.get_experiment(experiment_id)
        if exp is None:
            return None
        return _experiment_to_dict(exp)

    def get_results(self, experiment_id: str) -> dict[str, Any] | None:
        """Get analysis results for an experiment."""
        exp = self._service.get_experiment(experiment_id)
        if exp is None:
            return None
        try:
            return self._service.get_experiment_results(experiment_id)
        except ValueError:
            return None


def _experiment_to_dict(exp: Any) -> dict[str, Any]:
    """Convert an Experiment model to a JSON-serializable dict."""
    return {
        "id": exp.id,
        "name": exp.name,
        "description": exp.description,
        "status": exp.status.value if hasattr(exp.status, "value") else str(exp.status),
        "assignment_strategy": (
            exp.assignment_strategy.value
            if hasattr(exp.assignment_strategy, "value")
            else str(exp.assignment_strategy)
        ),
        "primary_metric": exp.primary_metric,
        "confidence_level": exp.confidence_level,
        "total_executions": exp.total_executions,
        "winner_variant_id": exp.winner_variant_id,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "started_at": exp.started_at.isoformat() if exp.started_at else None,
        "stopped_at": exp.stopped_at.isoformat() if exp.stopped_at else None,
        "tags": exp.tags if exp.tags else [],
    }
