"""Tests for GoalReviewWorkflow."""

import pytest

from src.goals._schemas import GoalReviewAction
from src.goals.models import GoalProposalRecord
from src.goals.review_workflow import GoalReviewWorkflow
from src.goals.store import GoalStore

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def store():
    return GoalStore(database_url=MEMORY_DB)


@pytest.fixture
def proposed_proposal(store):
    p = GoalProposalRecord(
        id="gp-review1",
        goal_type="cost_reduction",
        title="Test Proposal",
        description="Test",
        status="proposed",
        priority_score=0.5,
    )
    store.save_proposal(p)
    return p


class TestSubmitForReview:
    def test_submit_proposed(self, store, proposed_proposal):
        wf = GoalReviewWorkflow(store)
        ok = wf.submit_for_review("gp-review1")
        assert ok is True
        p = store.get_proposal("gp-review1")
        assert p.status == "under_review"

    def test_submit_nonexistent(self, store):
        wf = GoalReviewWorkflow(store)
        ok = wf.submit_for_review("nope")
        assert ok is False

    def test_submit_wrong_status(self, store):
        p = GoalProposalRecord(
            id="gp-approved",
            goal_type="cost_reduction",
            title="Already approved",
            description="Test",
            status="approved",
        )
        store.save_proposal(p)
        wf = GoalReviewWorkflow(store)
        ok = wf.submit_for_review("gp-approved")
        assert ok is False


class TestReview:
    def test_approve(self, store, proposed_proposal):
        wf = GoalReviewWorkflow(store)
        ok = wf.review("gp-review1", GoalReviewAction.APPROVE, "admin", "LGTM")
        assert ok is True
        p = store.get_proposal("gp-review1")
        assert p.status == "approved"
        assert p.reviewer == "admin"

    def test_reject(self, store, proposed_proposal):
        wf = GoalReviewWorkflow(store)
        ok = wf.review("gp-review1", GoalReviewAction.REJECT, "admin", "Not now")
        assert ok is True
        p = store.get_proposal("gp-review1")
        assert p.status == "rejected"

    def test_defer(self, store, proposed_proposal):
        wf = GoalReviewWorkflow(store)
        ok = wf.review("gp-review1", GoalReviewAction.DEFER, "admin")
        assert ok is True
        p = store.get_proposal("gp-review1")
        assert p.status == "deferred"

    def test_review_from_under_review(self, store):
        p = GoalProposalRecord(
            id="gp-ur",
            goal_type="cost_reduction",
            title="Under Review",
            description="Test",
            status="under_review",
        )
        store.save_proposal(p)
        wf = GoalReviewWorkflow(store)
        ok = wf.review("gp-ur", GoalReviewAction.APPROVE, "admin")
        assert ok is True

    def test_review_invalid_status(self, store):
        p = GoalProposalRecord(
            id="gp-done",
            goal_type="cost_reduction",
            title="Completed",
            description="Test",
            status="completed",
        )
        store.save_proposal(p)
        wf = GoalReviewWorkflow(store)
        ok = wf.review("gp-done", GoalReviewAction.APPROVE, "admin")
        assert ok is False

    def test_review_nonexistent(self, store):
        wf = GoalReviewWorkflow(store)
        ok = wf.review("nope", GoalReviewAction.APPROVE, "admin")
        assert ok is False


class TestListPendingReviews:
    def test_includes_proposed_and_under_review(self, store):
        p1 = GoalProposalRecord(
            id="gp-p1", goal_type="cost_reduction", title="P1",
            description="T", status="proposed",
        )
        p2 = GoalProposalRecord(
            id="gp-p2", goal_type="cost_reduction", title="P2",
            description="T", status="under_review",
        )
        p3 = GoalProposalRecord(
            id="gp-p3", goal_type="cost_reduction", title="P3",
            description="T", status="approved",
        )
        store.save_proposal(p1)
        store.save_proposal(p2)
        store.save_proposal(p3)
        wf = GoalReviewWorkflow(store)
        pending = wf.list_pending_reviews()
        ids = {p.id for p in pending}
        assert "gp-p1" in ids
        assert "gp-p2" in ids
        assert "gp-p3" not in ids


class TestAcceptanceRate:
    def test_no_decisions(self, store):
        wf = GoalReviewWorkflow(store)
        assert wf.get_acceptance_rate() == 0.0

    def test_mixed_decisions(self, store):
        for i in range(3):
            store.save_proposal(GoalProposalRecord(
                id=f"gp-a{i}", goal_type="cost_reduction",
                title=f"Approved {i}", description="T", status="approved",
            ))
        store.save_proposal(GoalProposalRecord(
            id="gp-r1", goal_type="cost_reduction",
            title="Rejected", description="T", status="rejected",
        ))
        wf = GoalReviewWorkflow(store)
        rate = wf.get_acceptance_rate()
        assert rate == pytest.approx(0.75)
