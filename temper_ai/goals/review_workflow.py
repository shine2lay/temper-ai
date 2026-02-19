"""Review workflow for goal proposals — approve, reject, defer lifecycle."""

import logging
from typing import List, Optional

from temper_ai.goals._schemas import GoalReviewAction, GoalStatus
from temper_ai.goals.models import GoalProposalRecord
from temper_ai.goals.safety_policy import GoalSafetyPolicy
from temper_ai.goals.store import GoalStore

logger = logging.getLogger(__name__)

# Valid status transitions
_TRANSITIONS = {
    GoalStatus.PROPOSED.value: {
        GoalReviewAction.APPROVE: GoalStatus.APPROVED.value,
        GoalReviewAction.REJECT: GoalStatus.REJECTED.value,
        GoalReviewAction.DEFER: GoalStatus.DEFERRED.value,
    },
    GoalStatus.UNDER_REVIEW.value: {
        GoalReviewAction.APPROVE: GoalStatus.APPROVED.value,
        GoalReviewAction.REJECT: GoalStatus.REJECTED.value,
        GoalReviewAction.DEFER: GoalStatus.DEFERRED.value,
    },
}


class GoalReviewWorkflow:
    """Manages the review lifecycle for goal proposals."""

    def __init__(
        self,
        store: GoalStore,
        safety_policy: Optional[GoalSafetyPolicy] = None,
    ) -> None:
        self._store = store
        self._safety_policy = safety_policy

    def submit_for_review(self, proposal_id: str) -> bool:
        """Move a proposal from PROPOSED to UNDER_REVIEW."""
        proposal = self._store.get_proposal(proposal_id)
        if proposal is None:
            logger.warning("Proposal not found: %s", proposal_id)
            return False

        if proposal.status != GoalStatus.PROPOSED.value:
            logger.warning(
                "Cannot submit %s for review (status=%s)",
                proposal_id,
                proposal.status,
            )
            return False

        return self._store.update_proposal_status(
            proposal_id, GoalStatus.UNDER_REVIEW.value
        )

    def review(
        self,
        proposal_id: str,
        action: GoalReviewAction,
        reviewer: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Apply a review decision to a proposal."""
        proposal = self._store.get_proposal(proposal_id)
        if proposal is None:
            logger.warning("Proposal not found: %s", proposal_id)
            return False

        valid_transitions = _TRANSITIONS.get(proposal.status)
        if valid_transitions is None:
            logger.warning(
                "No transitions from status '%s' for proposal %s",
                proposal.status,
                proposal_id,
            )
            return False

        new_status = valid_transitions.get(action)
        if new_status is None:
            logger.warning(
                "Invalid action '%s' for status '%s'",
                action.value,
                proposal.status,
            )
            return False

        ok = self._store.update_proposal_status(
            proposal_id,
            new_status,
            reviewer=reviewer,
            reason=reason,
        )
        if ok:
            logger.info(
                "Proposal %s: %s -> %s (by %s)",
                proposal_id,
                proposal.status,
                new_status,
                reviewer,
            )
        return ok

    def list_pending_reviews(self) -> List[GoalProposalRecord]:
        """List proposals awaiting review (proposed or under_review)."""
        proposed = self._store.list_proposals(
            status=GoalStatus.PROPOSED.value
        )
        under_review = self._store.list_proposals(
            status=GoalStatus.UNDER_REVIEW.value
        )
        return proposed + under_review

    def get_acceptance_rate(self) -> float:
        """Calculate approval rate. Returns 0.0 if no decisions yet."""
        counts = self._store.count_by_status()
        approved = counts.get(GoalStatus.APPROVED.value, 0)
        rejected = counts.get(GoalStatus.REJECTED.value, 0)
        total = approved + rejected
        if total == 0:
            return 0.0
        return approved / total
