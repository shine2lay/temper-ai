"""FastAPI routes for goal proposal dashboard."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from temper_ai.goals.dashboard_service import GoalDataService

HTTP_404 = 404
REVIEW_FAIL_MSG = "Proposal not found or invalid transition"


def _apply_review(
    goal_service: GoalDataService,
    proposal_id: str,
    action_name: str,
    reviewer: str,
    reason: Optional[str],
) -> Dict[str, Any]:
    """Apply a review action and return result or raise 404."""
    from temper_ai.goals._schemas import GoalReviewAction
    from temper_ai.goals.review_workflow import GoalReviewWorkflow

    action = GoalReviewAction(action_name)
    workflow = GoalReviewWorkflow(store=goal_service.store)
    ok = workflow.review(proposal_id, action, reviewer, reason)
    if not ok:
        raise HTTPException(status_code=HTTP_404, detail=REVIEW_FAIL_MSG)
    return {"id": proposal_id, "status": action_name}


def create_goals_router(goal_service: GoalDataService) -> APIRouter:
    """Create goal proposal API router."""
    router = APIRouter(prefix="/goals", tags=["goals"])
    _register_query_routes(router, goal_service)
    _register_action_routes(router, goal_service)
    return router


def _register_query_routes(
    router: APIRouter, goal_service: GoalDataService,
) -> None:
    """Register read-only query endpoints."""

    @router.get("/proposals")
    def get_proposals(
        status: Optional[str] = None,
        goal_type: Optional[str] = None,
        limit: int = 50,  # noqa: scanner: skip-magic
    ) -> List[Dict[str, Any]]:
        """List proposals with optional filters."""
        return goal_service.get_proposals(
            status=status, goal_type=goal_type, limit=limit
        )

    @router.get("/proposals/{proposal_id}")
    def get_proposal(proposal_id: str) -> Dict[str, Any]:
        """Get single proposal detail."""
        detail = goal_service.get_proposal_detail(proposal_id)
        if detail is None:
            raise HTTPException(
                status_code=HTTP_404, detail="Proposal not found"
            )
        return detail

    @router.get("/stats")
    def get_stats() -> Dict[str, Any]:
        """Get proposal statistics."""
        return goal_service.get_stats()

    @router.get("/analysis-runs")
    def get_analysis_runs() -> List[Dict[str, Any]]:
        """Get recent analysis runs."""
        return goal_service.get_analysis_runs()


def _register_action_routes(
    router: APIRouter, goal_service: GoalDataService,
) -> None:
    """Register mutation endpoints."""

    @router.post("/analyze")
    def trigger_analysis() -> Dict[str, Any]:
        """Trigger an analysis run."""
        from temper_ai.goals.analysis_orchestrator import AnalysisOrchestrator

        orch = AnalysisOrchestrator(store=goal_service.store)
        run = orch.run_analysis()
        return {
            "id": run.id,
            "status": run.status,
            "proposals_generated": run.proposals_generated,
        }

    @router.post("/proposals/{proposal_id}/approve")
    def approve_proposal(
        proposal_id: str,
        reviewer: str = "dashboard",
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve a proposal."""
        return _apply_review(goal_service, proposal_id, "approve", reviewer, reason)

    @router.post("/proposals/{proposal_id}/reject")
    def reject_proposal(
        proposal_id: str,
        reviewer: str = "dashboard",
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reject a proposal."""
        return _apply_review(goal_service, proposal_id, "reject", reviewer, reason)

    @router.post("/proposals/{proposal_id}/defer")
    def defer_proposal(
        proposal_id: str,
        reviewer: str = "dashboard",
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Defer a proposal."""
        return _apply_review(goal_service, proposal_id, "defer", reviewer, reason)
