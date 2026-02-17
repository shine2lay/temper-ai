"""FastAPI routes for experimentation dashboard."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from src.experimentation.dashboard_service import ExperimentDataService

HTTP_404 = 404
HTTP_400 = 400


def create_experimentation_router(service: ExperimentDataService) -> APIRouter:
    """Create experimentation API router."""
    router = APIRouter(prefix="/experiments", tags=["experimentation"])
    _register_query_routes(router, service)
    _register_action_routes(router, service)
    return router


def _register_query_routes(
    router: APIRouter, service: ExperimentDataService,
) -> None:
    """Register read-only query endpoints."""

    @router.get("")
    def list_experiments(
        status: Optional[str] = None,
        limit: int = 50,  # noqa: scanner: skip-magic
    ) -> List[Dict[str, Any]]:
        """List experiments with optional status filter."""
        try:
            return service.list_experiments(status=status, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=HTTP_400, detail=str(exc))

    @router.get("/{experiment_id}")
    def get_experiment(experiment_id: str) -> Dict[str, Any]:
        """Get a single experiment."""
        result = service.get_experiment(experiment_id)
        if result is None:
            raise HTTPException(
                status_code=HTTP_404, detail="Experiment not found"
            )
        return result

    @router.get("/{experiment_id}/results")
    def get_results(experiment_id: str) -> Dict[str, Any]:
        """Get analysis results for an experiment."""
        result = service.get_results(experiment_id)
        if result is None:
            raise HTTPException(
                status_code=HTTP_404,
                detail="Experiment not found or no results available",
            )
        return result


def _register_action_routes(
    router: APIRouter, service: ExperimentDataService,
) -> None:
    """Register mutation endpoints."""

    @router.post("")
    def create_experiment(body: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new experiment."""
        try:
            name = body.get("name", "")
            description = body.get("description", "")
            variants = body.get("variants", [])
            if not name or not variants:
                raise ValueError("name and variants are required")
            exp_id = service._service.create_experiment(
                name=name,
                description=description,
                variants=variants,
                primary_metric=body.get("primary_metric", "duration_seconds"),
                tags=body.get("tags"),
            )
            return {"id": exp_id, "status": "created"}
        except ValueError as exc:
            raise HTTPException(status_code=HTTP_400, detail=str(exc))

    @router.post("/{experiment_id}/start")
    def start_experiment(experiment_id: str) -> Dict[str, Any]:
        """Start an experiment."""
        try:
            service._service.start_experiment(experiment_id)
            return {"id": experiment_id, "status": "running"}
        except ValueError as exc:
            raise HTTPException(status_code=HTTP_400, detail=str(exc))

    @router.post("/{experiment_id}/stop")
    def stop_experiment(experiment_id: str) -> Dict[str, Any]:
        """Stop an experiment."""
        try:
            service._service.stop_experiment(experiment_id)
            return {"id": experiment_id, "status": "stopped"}
        except ValueError as exc:
            raise HTTPException(status_code=HTTP_400, detail=str(exc))
