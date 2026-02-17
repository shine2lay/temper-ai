"""Tests for goal CLI commands."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.goals.models import AnalysisRun, GoalProposalRecord
from src.interfaces.cli.goal_commands import goals_group

MEMORY_DB = "sqlite:///:memory:"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_store():
    with patch("src.interfaces.cli.goal_commands._get_store") as mock:
        store = MagicMock()
        mock.return_value = store
        yield store


class TestListCommand:
    def test_empty(self, runner, mock_store):
        mock_store.list_proposals.return_value = []
        result = runner.invoke(goals_group, ["list"])
        assert result.exit_code == 0
        assert "No proposals" in result.output

    def test_with_proposals(self, runner, mock_store):
        mock_store.list_proposals.return_value = [
            GoalProposalRecord(
                id="gp-test001",
                goal_type="cost_reduction",
                title="Reduce costs",
                description="Switch model",
                status="proposed",
                priority_score=0.75,
                risk_assessment={"level": "low"},
            )
        ]
        result = runner.invoke(goals_group, ["list"])
        assert result.exit_code == 0
        assert "Reduce costs" in result.output

    def test_with_filters(self, runner, mock_store):
        mock_store.list_proposals.return_value = []
        runner.invoke(goals_group, ["list", "--status", "approved", "--type", "cost_reduction"])
        mock_store.list_proposals.assert_called_once_with(
            status="approved",
            goal_type="cost_reduction",
            product_type=None,
            limit=20,
        )


class TestProposeCommand:
    def test_propose(self, runner):
        with patch("src.interfaces.cli.goal_commands._get_store"), \
             patch("src.interfaces.cli.goal_commands.AnalysisOrchestrator", create=True) as MockOrch:
            # We need to mock the import inside the function
            with patch("src.goals.analysis_orchestrator.AnalysisOrchestrator") as RealOrch:
                run = AnalysisRun(id="ar-1", status="completed", proposals_generated=3)
                RealOrch.return_value.run_analysis.return_value = run
                with patch("src.interfaces.cli.goal_commands._get_store") as mock_gs:
                    mock_gs.return_value = MagicMock()
                    result = runner.invoke(goals_group, ["propose"])
                    assert result.exit_code == 0


class TestStatusCommand:
    def test_status(self, runner, mock_store):
        mock_store.count_by_status.return_value = {"proposed": 5, "approved": 3}
        mock_store.list_analysis_runs.return_value = []
        with patch("src.goals.review_workflow.GoalReviewWorkflow") as MockWf:
            MockWf.return_value.get_acceptance_rate.return_value = 0.6
            result = runner.invoke(goals_group, ["status"])
        assert result.exit_code == 0


class TestApproveCommand:
    def test_approve(self, runner, mock_store):
        with patch("src.goals.review_workflow.GoalReviewWorkflow") as MockWf:
            MockWf.return_value.review.return_value = True
            result = runner.invoke(
                goals_group, ["approve", "gp-1", "--reviewer", "admin"]
            )
        assert result.exit_code == 0
        assert "Approved" in result.output


class TestRejectCommand:
    def test_reject(self, runner, mock_store):
        with patch("src.goals.review_workflow.GoalReviewWorkflow") as MockWf:
            MockWf.return_value.review.return_value = True
            result = runner.invoke(
                goals_group, ["reject", "gp-1", "--reviewer", "admin"]
            )
        assert result.exit_code == 0
        assert "Rejected" in result.output


class TestReviewCommand:
    def test_review_defer(self, runner, mock_store):
        with patch("src.goals.review_workflow.GoalReviewWorkflow") as MockWf:
            MockWf.return_value.review.return_value = True
            result = runner.invoke(
                goals_group,
                ["review", "gp-1", "--action", "defer", "--reviewer", "admin"],
            )
        assert result.exit_code == 0
        assert "defer" in result.output.lower()
