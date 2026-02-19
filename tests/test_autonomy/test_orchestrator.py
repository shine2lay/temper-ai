"""Tests for the PostExecutionOrchestrator."""

import time
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.autonomy._schemas import (
    AutonomousLoopConfig,
    PostExecutionReport,
    WorkflowRunContext,
)
from temper_ai.autonomy.orchestrator import PostExecutionOrchestrator


def _make_context(**overrides: object) -> WorkflowRunContext:
    """Create a test WorkflowRunContext with sensible defaults."""
    defaults = {
        "workflow_id": "wf-test-001",
        "workflow_name": "test_workflow",
        "product_type": "api",
        "result": {"status": "completed"},
        "duration_seconds": 10.0,
        "status": "completed",
        "cost_usd": 0.02,
        "total_tokens": 500,
    }
    defaults.update(overrides)
    return WorkflowRunContext(**defaults)


class TestOrchestratorDisabled:
    """Tests when the autonomous loop is disabled."""

    def test_disabled_returns_empty_report(self) -> None:
        config = AutonomousLoopConfig(enabled=False)
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())
        assert report.learning_result is None
        assert report.goals_result is None
        assert report.portfolio_result is None
        assert report.errors == []

    def test_disabled_by_default(self) -> None:
        config = AutonomousLoopConfig()
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())
        assert report.learning_result is None


class TestOrchestratorEnabled:
    """Tests when subsystems are enabled."""

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_all_subsystems_called(
        self, mock_learning: MagicMock, mock_goals: MagicMock, mock_portfolio: MagicMock
    ) -> None:
        mock_learning.return_value = {"patterns_found": 2}
        mock_goals.return_value = {"proposals_generated": 1}
        mock_portfolio.return_value = {"scorecards": 1}

        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        ctx = _make_context()
        report = orch.run(ctx)

        mock_learning.assert_called_once()
        mock_goals.assert_called_once()
        mock_portfolio.assert_called_once()
        assert report.learning_result == {"patterns_found": 2}
        assert report.goals_result == {"proposals_generated": 1}
        assert report.portfolio_result == {"scorecards": 1}
        assert report.duration_ms >= 0

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_selective_disable_learning(
        self, mock_learning: MagicMock, mock_goals: MagicMock, mock_portfolio: MagicMock
    ) -> None:
        mock_goals.return_value = {"proposals_generated": 0}
        mock_portfolio.return_value = {"scorecards": 0}

        config = AutonomousLoopConfig(
            enabled=True, learning_enabled=False
        )
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        mock_learning.assert_not_called()
        mock_goals.assert_called_once()
        mock_portfolio.assert_called_once()
        assert report.learning_result is None

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_selective_disable_goals(
        self, mock_learning: MagicMock, mock_goals: MagicMock, mock_portfolio: MagicMock
    ) -> None:
        mock_learning.return_value = {"patterns_found": 0}
        mock_portfolio.return_value = {"scorecards": 0}

        config = AutonomousLoopConfig(
            enabled=True, goals_enabled=False
        )
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        mock_goals.assert_not_called()
        assert report.goals_result is None

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_selective_disable_portfolio(
        self, mock_learning: MagicMock, mock_goals: MagicMock, mock_portfolio: MagicMock
    ) -> None:
        mock_learning.return_value = {"patterns_found": 0}
        mock_goals.return_value = {"proposals_generated": 0}

        config = AutonomousLoopConfig(
            enabled=True, portfolio_enabled=False
        )
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        mock_portfolio.assert_not_called()
        assert report.portfolio_result is None


class TestOrchestratorGracefulDegradation:
    """Tests for graceful degradation when subsystems fail."""

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_learning_failure_doesnt_crash(
        self, mock_learning: MagicMock, mock_goals: MagicMock, mock_portfolio: MagicMock
    ) -> None:
        mock_learning.return_value = None
        mock_goals.return_value = {"proposals_generated": 1}
        mock_portfolio.return_value = {"scorecards": 1}

        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        # Learning failed, but goals and portfolio still ran
        assert report.learning_result is None
        assert report.goals_result is not None
        assert report.portfolio_result is not None

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_all_subsystems_fail(
        self, mock_learning: MagicMock, mock_goals: MagicMock, mock_portfolio: MagicMock
    ) -> None:
        mock_learning.return_value = None
        mock_goals.return_value = None
        mock_portfolio.return_value = None

        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        assert report.learning_result is None
        assert report.goals_result is None
        assert report.portfolio_result is None


class TestOrchestratorLearningIntegration:
    """Tests for _run_learning with mocked stores."""

    def test_learning_import_error_graceful(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        with patch(
            "temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning",
            side_effect=None,
        ):
            # Simulate import error in the actual method
            pass

        # Direct test of _run_learning with import mock
        with patch.dict("sys.modules", {"temper_ai.learning.orchestrator": None}):
            result = orch._run_learning(ctx, report)
            assert result is None
            assert len(report.errors) == 1

    def test_learning_with_mocked_stores(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        mock_mining_run = MagicMock()
        mock_mining_run.id = "mr-001"
        mock_mining_run.patterns_found = 3
        mock_mining_run.patterns_new = 1
        mock_mining_run.status = "completed"

        with patch("temper_ai.learning.store.LearningStore") as MockStore, \
             patch("temper_ai.learning.orchestrator.MiningOrchestrator") as MockMining, \
             patch("temper_ai.learning.recommender.RecommendationEngine") as MockEngine:
            MockStore.return_value = MagicMock()
            MockMining.return_value.run_mining.return_value = mock_mining_run
            MockEngine.return_value.generate_recommendations.return_value = ["rec1"]

            result = orch._run_learning(ctx, report)

        assert result is not None
        assert result["patterns_found"] == 3
        assert result["patterns_new"] == 1
        assert result["recommendations"] == 1
        assert result["status"] == "completed"
        assert len(report.errors) == 0


class TestOrchestratorGoalsIntegration:
    """Tests for _run_goals with mocked stores."""

    def test_goals_with_mocked_stores(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        mock_analysis_run = MagicMock()
        mock_analysis_run.id = "ar-001"
        mock_analysis_run.proposals_generated = 2
        mock_analysis_run.status = "completed"

        with patch("temper_ai.goals.store.GoalStore") as MockStore, \
             patch("temper_ai.goals.analysis_orchestrator.AnalysisOrchestrator") as MockOrch:
            MockStore.return_value = MagicMock()
            MockOrch.return_value.run_analysis.return_value = mock_analysis_run

            result = orch._run_goals(ctx, report)

        assert result is not None
        assert result["proposals_generated"] == 2
        assert result["status"] == "completed"
        assert len(report.errors) == 0

    def test_goals_exception_is_captured(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        with patch("temper_ai.goals.store.GoalStore", side_effect=RuntimeError("db error")):
            result = orch._run_goals(ctx, report)

        assert result is None
        assert len(report.errors) == 1
        assert "Goals" in report.errors[0]


class TestOrchestratorPortfolioIntegration:
    """Tests for _run_portfolio with mocked stores."""

    def test_portfolio_with_product_type(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context(product_type="api")

        # Mock a portfolio record whose config dict contains a matching product
        mock_record = MagicMock()
        mock_record.config = {
            "name": "test",
            "products": [{"name": "api"}],
        }

        with patch("temper_ai.portfolio.store.PortfolioStore") as MockStore, \
             patch("temper_ai.portfolio.optimizer.PortfolioOptimizer") as MockOpt:
            MockStore.return_value.list_portfolios.return_value = [mock_record]
            MockOpt.return_value.compute_scorecards.return_value = [MagicMock()]
            MockOpt.return_value.recommend.return_value = [MagicMock()]

            result = orch._run_portfolio(ctx, report)

        assert result is not None
        assert result["product_type"] == "api"
        assert result["scorecards"] == 1
        assert result["recommendations"] == 1

    def test_portfolio_without_product_type_skips(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context(product_type=None)

        with patch("temper_ai.portfolio.store.PortfolioStore") as MockStore:
            MockStore.return_value = MagicMock()
            result = orch._run_portfolio(ctx, report)

        assert result is not None
        assert result["skipped"] is True

    def test_portfolio_exception_is_captured(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        with patch("temper_ai.portfolio.store.PortfolioStore", side_effect=RuntimeError("db error")):
            result = orch._run_portfolio(ctx, report)

        assert result is None
        assert len(report.errors) == 1
        assert "Portfolio" in report.errors[0]


class TestWorkflowSchemaBackwardCompat:
    """Tests that existing workflow YAMLs still parse with the new field."""

    def test_workflow_schema_without_autonomous_loop(self) -> None:
        from temper_ai.workflow._schemas import WorkflowConfig

        config_data = {
            "workflow": {
                "name": "test",
                "description": "test workflow",
                "stages": [
                    {"name": "s1", "stage_ref": "configs/stages/s1.yaml"}
                ],
                "error_handling": {
                    "on_stage_failure": "halt",
                    "escalation_policy": "default",
                },
            }
        }
        parsed = WorkflowConfig(**config_data)
        assert parsed.workflow.autonomous_loop.enabled is False

    def test_workflow_schema_with_autonomous_loop(self) -> None:
        from temper_ai.workflow._schemas import WorkflowConfig

        config_data = {
            "workflow": {
                "name": "test",
                "description": "test workflow",
                "stages": [
                    {"name": "s1", "stage_ref": "configs/stages/s1.yaml"}
                ],
                "autonomous_loop": {
                    "enabled": True,
                    "learning_enabled": True,
                    "goals_enabled": False,
                },
                "error_handling": {
                    "on_stage_failure": "halt",
                    "escalation_policy": "default",
                },
            }
        }
        parsed = WorkflowConfig(**config_data)
        assert parsed.workflow.autonomous_loop.enabled is True
        assert parsed.workflow.autonomous_loop.learning_enabled is True
        assert parsed.workflow.autonomous_loop.goals_enabled is False
        assert parsed.workflow.autonomous_loop.portfolio_enabled is True


class TestOrchestratorFeedbackWiring:
    """Tests for feedback subsystem wiring in the orchestrator."""

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_feedback")
    def test_feedback_called_when_auto_apply_learning(
        self,
        mock_feedback: MagicMock,
        mock_learning: MagicMock,
        mock_goals: MagicMock,
        mock_portfolio: MagicMock,
    ) -> None:
        mock_learning.return_value = {"patterns_found": 1}
        mock_goals.return_value = {"proposals_generated": 0}
        mock_portfolio.return_value = {"scorecards": 0}
        mock_feedback.return_value = {"learning": []}

        config = AutonomousLoopConfig(
            enabled=True, auto_apply_learning=True,
        )
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        mock_feedback.assert_called_once()
        assert report.feedback_result == {"learning": []}

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_feedback")
    def test_feedback_called_when_auto_apply_goals(
        self,
        mock_feedback: MagicMock,
        mock_learning: MagicMock,
        mock_goals: MagicMock,
        mock_portfolio: MagicMock,
    ) -> None:
        mock_learning.return_value = {"patterns_found": 0}
        mock_goals.return_value = {"proposals_generated": 1}
        mock_portfolio.return_value = {"scorecards": 0}
        mock_feedback.return_value = {"goals": []}

        config = AutonomousLoopConfig(
            enabled=True, auto_apply_goals=True,
        )
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        mock_feedback.assert_called_once()
        assert report.feedback_result == {"goals": []}

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_feedback_not_called_when_disabled(
        self,
        mock_learning: MagicMock,
        mock_goals: MagicMock,
        mock_portfolio: MagicMock,
    ) -> None:
        mock_learning.return_value = {"patterns_found": 0}
        mock_goals.return_value = {"proposals_generated": 0}
        mock_portfolio.return_value = {"scorecards": 0}

        config = AutonomousLoopConfig(
            enabled=True,
            auto_apply_learning=False,
            auto_apply_goals=False,
        )
        orch = PostExecutionOrchestrator(config)
        report = orch.run(_make_context())

        assert report.feedback_result is None


class TestOrchestratorMemoryBridge:
    """Tests for memory bridge wiring in _run_learning."""

    def test_memory_sync_result_set_after_learning(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        mock_mining_run = MagicMock()
        mock_mining_run.id = "mr-001"
        mock_mining_run.patterns_found = 2
        mock_mining_run.patterns_new = 1
        mock_mining_run.status = "completed"

        with patch("temper_ai.learning.store.LearningStore") as MockStore, \
             patch("temper_ai.learning.orchestrator.MiningOrchestrator") as MockMining, \
             patch("temper_ai.learning.recommender.RecommendationEngine") as MockEngine, \
             patch("temper_ai.autonomy.memory_bridge.LearningToMemoryBridge") as MockBridge:
            MockStore.return_value = MagicMock()
            MockMining.return_value.run_mining.return_value = mock_mining_run
            MockEngine.return_value.generate_recommendations.return_value = []
            MockBridge.return_value.sync_patterns_to_memory.return_value = 3

            result = orch._run_learning(ctx, report)

        assert result is not None
        assert report.memory_sync_result == {"patterns_synced": 3}

    def test_memory_bridge_failure_does_not_crash_learning(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        mock_mining_run = MagicMock()
        mock_mining_run.id = "mr-002"
        mock_mining_run.patterns_found = 1
        mock_mining_run.patterns_new = 0
        mock_mining_run.status = "completed"

        with patch("temper_ai.learning.store.LearningStore") as MockStore, \
             patch("temper_ai.learning.orchestrator.MiningOrchestrator") as MockMining, \
             patch("temper_ai.learning.recommender.RecommendationEngine") as MockEngine, \
             patch("temper_ai.autonomy.memory_bridge.LearningToMemoryBridge") as MockBridge:
            MockStore.return_value = MagicMock()
            MockMining.return_value.run_mining.return_value = mock_mining_run
            MockEngine.return_value.generate_recommendations.return_value = []
            MockBridge.return_value.sync_patterns_to_memory.side_effect = RuntimeError("memory error")

            result = orch._run_learning(ctx, report)

        # Learning should still succeed even if bridge fails
        assert result is not None
        assert result["patterns_found"] == 1
        assert report.memory_sync_result is None


class TestOrchestratorTimeout:
    """Tests for timeout enforcement in the orchestrator."""

    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_portfolio")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_goals")
    @patch("temper_ai.autonomy.orchestrator.PostExecutionOrchestrator._run_learning")
    def test_timeout_skips_remaining_subsystems(
        self,
        mock_learning: MagicMock,
        mock_goals: MagicMock,
        mock_portfolio: MagicMock,
    ) -> None:
        # Make learning "take too long" by patching time.monotonic
        call_count = 0
        real_monotonic = time.monotonic

        def fake_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            # First call is at start; second call is in _budget_exhausted after learning
            # Return a value exceeding 300s after the first check
            if call_count <= 1:
                return real_monotonic()
            return real_monotonic() + 400

        mock_learning.return_value = {"patterns_found": 1}

        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)

        with patch("temper_ai.autonomy.orchestrator.time.monotonic", side_effect=fake_monotonic):
            report = orch.run(_make_context())

        # Learning was called
        mock_learning.assert_called_once()
        # Goals and portfolio should have been skipped due to timeout
        mock_goals.assert_not_called()
        mock_portfolio.assert_not_called()
        assert any("Timeout" in e for e in report.errors)

    def test_budget_exhausted_returns_false_within_timeout(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        start = time.monotonic()
        assert orch._budget_exhausted(start, report) is False
        assert report.errors == []


class TestOrchestratorGoalAnalyzers:
    """Tests that analyzers are passed to AnalysisOrchestrator in _run_goals."""

    def test_analyzers_passed_to_orchestrator(self) -> None:
        config = AutonomousLoopConfig(enabled=True)
        orch = PostExecutionOrchestrator(config)
        report = PostExecutionReport()
        ctx = _make_context()

        mock_analysis_run = MagicMock()
        mock_analysis_run.id = "ar-001"
        mock_analysis_run.proposals_generated = 0
        mock_analysis_run.status = "completed"

        with patch("temper_ai.goals.store.GoalStore") as MockGoalStore, \
             patch("temper_ai.learning.store.LearningStore") as MockLearningStore, \
             patch("temper_ai.goals.analysis_orchestrator.AnalysisOrchestrator") as MockOrch, \
             patch("temper_ai.goals.analyzers.performance.PerformanceAnalyzer"), \
             patch("temper_ai.goals.analyzers.reliability.ReliabilityAnalyzer"), \
             patch("temper_ai.goals.analyzers.cost.CostAnalyzer"), \
             patch("temper_ai.goals.analyzers.cross_product.CrossProductAnalyzer"):
            MockGoalStore.return_value = MagicMock()
            MockLearningStore.return_value = MagicMock()
            MockOrch.return_value.run_analysis.return_value = mock_analysis_run

            result = orch._run_goals(ctx, report)

        assert result is not None
        # Verify AnalysisOrchestrator was constructed with analyzers kwarg
        call_kwargs = MockOrch.call_args
        assert "analyzers" in call_kwargs.kwargs
        assert len(call_kwargs.kwargs["analyzers"]) > 0
        # learning_store should be a LearningStore, not a GoalStore
        assert call_kwargs.kwargs["learning_store"] is MockLearningStore.return_value


class TestPostExecutionReportNewFields:
    """Tests for the new fields on PostExecutionReport."""

    def test_feedback_result_defaults_to_none(self) -> None:
        report = PostExecutionReport()
        assert report.feedback_result is None

    def test_memory_sync_result_defaults_to_none(self) -> None:
        report = PostExecutionReport()
        assert report.memory_sync_result is None

    def test_new_fields_can_be_set(self) -> None:
        report = PostExecutionReport(
            feedback_result={"learning": []},
            memory_sync_result={"patterns_synced": 5},
        )
        assert report.feedback_result == {"learning": []}
        assert report.memory_sync_result["patterns_synced"] == 5
