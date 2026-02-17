"""Data service for goal proposal dashboard endpoints."""

from typing import Any, Dict, List, Optional

from src.goals.review_workflow import GoalReviewWorkflow
from src.goals.store import GoalStore

DEFAULT_PROPOSAL_LIMIT = 50
DEFAULT_RUN_LIMIT = 20


class GoalDataService:
    """Provides data for goal dashboard endpoints."""

    def __init__(self, store: GoalStore) -> None:
        self.store = store
        self._review = GoalReviewWorkflow(store)

    def get_proposals(
        self,
        status: Optional[str] = None,
        goal_type: Optional[str] = None,
        limit: int = DEFAULT_PROPOSAL_LIMIT,
    ) -> List[Dict[str, Any]]:
        """Get proposals for display."""
        proposals = self.store.list_proposals(
            status=status, goal_type=goal_type, limit=limit
        )
        return [
            {
                "id": p.id,
                "goal_type": p.goal_type,
                "title": p.title,
                "status": p.status,
                "priority_score": p.priority_score,
                "effort_estimate": p.effort_estimate,
                "risk_assessment": p.risk_assessment,
                "created_at": (
                    p.created_at.isoformat() if p.created_at else None
                ),
            }
            for p in proposals
        ]

    def get_proposal_detail(
        self, proposal_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get full proposal detail."""
        p = self.store.get_proposal(proposal_id)
        if p is None:
            return None
        return {
            "id": p.id,
            "goal_type": p.goal_type,
            "title": p.title,
            "description": p.description,
            "status": p.status,
            "priority_score": p.priority_score,
            "effort_estimate": p.effort_estimate,
            "risk_assessment": p.risk_assessment,
            "expected_impacts": p.expected_impacts,
            "evidence": p.evidence,
            "source_product_type": p.source_product_type,
            "applicable_product_types": p.applicable_product_types,
            "proposed_actions": p.proposed_actions,
            "reviewer": p.reviewer,
            "review_reason": p.review_reason,
            "reviewed_at": (
                p.reviewed_at.isoformat() if p.reviewed_at else None
            ),
            "created_at": (
                p.created_at.isoformat() if p.created_at else None
            ),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics."""
        counts = self.store.count_by_status()
        acceptance_rate = self._review.get_acceptance_rate()
        return {
            "counts_by_status": counts,
            "total": sum(counts.values()),
            "acceptance_rate": acceptance_rate,
        }

    def get_analysis_runs(
        self, limit: int = DEFAULT_RUN_LIMIT
    ) -> List[Dict[str, Any]]:
        """Get recent analysis runs."""
        runs = self.store.list_analysis_runs(limit=limit)
        return [
            {
                "id": r.id,
                "started_at": (
                    r.started_at.isoformat() if r.started_at else None
                ),
                "completed_at": (
                    r.completed_at.isoformat() if r.completed_at else None
                ),
                "status": r.status,
                "proposals_generated": r.proposals_generated,
                "analyzer_stats": r.analyzer_stats,
            }
            for r in runs
        ]
