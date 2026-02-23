"""FastAPI routes for learning dashboard."""

from typing import Any

from fastapi import APIRouter, HTTPException

from temper_ai.learning.dashboard_service import LearningDataService

HTTP_404 = 404


def create_learning_router(learning_service: LearningDataService) -> APIRouter:
    """Create learning API router."""
    router = APIRouter(prefix="/learning", tags=["learning"])

    @router.get("/patterns")
    def get_patterns() -> dict[str, Any]:
        """Get pattern summary and top patterns."""
        return learning_service.get_pattern_summary()

    @router.get("/mining-runs")
    def get_mining_runs() -> list[dict[str, Any]]:
        """Get mining run history."""
        return learning_service.get_mining_history()

    @router.get("/convergence")
    def get_convergence() -> dict[str, Any]:
        """Get convergence trend data."""
        return learning_service.get_convergence_data()

    @router.get("/recommendations")
    def get_recommendations() -> list[dict[str, Any]]:
        """Get pending recommendations."""
        return learning_service.get_recommendations()

    @router.post("/mine")
    def trigger_mine() -> dict[str, Any]:
        """Trigger a mining run."""
        from temper_ai.learning.orchestrator import MiningOrchestrator

        orch = MiningOrchestrator(store=learning_service.store)
        run = orch.run_mining()
        return {
            "id": run.id,
            "patterns_found": run.patterns_found,
            "patterns_new": run.patterns_new,
            "novelty_score": run.novelty_score,
        }

    @router.post("/recommendations/{rec_id}/apply")
    def apply_recommendation(rec_id: str) -> dict[str, Any]:
        """Mark a recommendation as applied."""
        ok = learning_service.store.update_recommendation_status(rec_id, "applied")
        if not ok:
            raise HTTPException(status_code=HTTP_404, detail="Recommendation not found")
        return {"id": rec_id, "status": "applied"}

    @router.post("/recommendations/{rec_id}/dismiss")
    def dismiss_recommendation(rec_id: str) -> dict[str, Any]:
        """Dismiss a recommendation."""
        ok = learning_service.store.update_recommendation_status(rec_id, "dismissed")
        if not ok:
            raise HTTPException(status_code=HTTP_404, detail="Recommendation not found")
        return {"id": rec_id, "status": "dismissed"}

    return router
