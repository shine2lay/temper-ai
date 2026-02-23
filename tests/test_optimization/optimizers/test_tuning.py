"""Tests for TuningOptimizer."""

from unittest.mock import MagicMock

import pytest

from temper_ai.optimization._schemas import EvaluationResult
from temper_ai.optimization.optimizers.tuning import TuningOptimizer


class TestTuningOptimizer:
    def _make_evaluator(self, results):
        evaluator = MagicMock()
        evaluator.evaluate.side_effect = results
        return evaluator

    def test_no_strategies_single_run(self):
        runner = MagicMock()
        runner.execute.return_value = {"result": "baseline"}
        evaluator = self._make_evaluator(
            [
                EvaluationResult(passed=True, score=0.7),
            ]
        )
        optimizer = TuningOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"strategies": []}
        )

        assert result.output == {"result": "baseline"}

    def test_multiple_strategies(self):
        runner = MagicMock()
        runner.execute.side_effect = [
            {"result": "v1"},
            {"result": "v2"},
        ]
        evaluator = self._make_evaluator(
            [
                EvaluationResult(passed=False, score=0.4),
                EvaluationResult(passed=True, score=0.9),
            ]
        )
        optimizer = TuningOptimizer()

        result = optimizer.optimize(
            runner,
            {"input": "data"},
            evaluator,
            {
                "strategies": [
                    {"name": "strategy_a"},
                    {"name": "strategy_b"},
                ],
                "runs": 1,
            },
        )

        assert result.score == pytest.approx(0.9)
        assert "strategy_scores" in result.details

    def test_with_experiment_service(self):
        mock_service = MagicMock()
        mock_service.create_experiment.return_value = "exp-123"
        mock_service.check_early_stopping.return_value = {"should_stop": False}
        mock_service.get_experiment_results.return_value = {
            "recommended_winner": "v1",
            "confidence": 0.85,
        }

        runner = MagicMock()
        runner.execute.return_value = {"result": "tuned"}
        evaluator = self._make_evaluator(
            [
                EvaluationResult(passed=True, score=0.8),
            ]
        )
        optimizer = TuningOptimizer(experiment_service=mock_service)

        result = optimizer.optimize(
            runner,
            {"input": "data"},
            evaluator,
            {
                "strategies": [{"name": "v1"}],
                "runs": 1,
            },
        )

        assert result.output == {"result": "tuned"}
        assert result.experiment_id == "exp-123"
        assert result.experiment_results is not None
        mock_service.create_experiment.assert_called_once()
        mock_service.start_experiment.assert_called_once_with("exp-123")
        mock_service.assign_variant.assert_called_once()
        mock_service.track_execution_complete.assert_called_once()
        mock_service.get_experiment_results.assert_called_once_with("exp-123")
        mock_service.stop_experiment.assert_called_once()

    def test_early_stopping(self):
        mock_service = MagicMock()
        mock_service.create_experiment.return_value = "exp-456"
        mock_service.check_early_stopping.return_value = {"should_stop": True}
        mock_service.get_experiment_results.return_value = {
            "recommended_winner": "v1",
        }

        runner = MagicMock()
        runner.execute.return_value = {"result": "v1"}
        evaluator = self._make_evaluator(
            [
                EvaluationResult(passed=True, score=0.9),
            ]
        )
        optimizer = TuningOptimizer(experiment_service=mock_service)

        result = optimizer.optimize(
            runner,
            {"input": "data"},
            evaluator,
            {
                "strategies": [{"name": "v1"}, {"name": "v2"}],
                "runs": 1,
            },
        )

        # Should stop after first strategy due to early stopping
        assert result.output == {"result": "v1"}
        assert runner.execute.call_count == 1

    def test_missing_service_fallback(self):
        runner = MagicMock()
        runner.execute.return_value = {"result": "fallback"}
        evaluator = self._make_evaluator(
            [
                EvaluationResult(passed=True, score=0.7),
            ]
        )
        optimizer = TuningOptimizer(experiment_service=None)

        result = optimizer.optimize(
            runner,
            {"input": "data"},
            evaluator,
            {
                "strategies": [{"name": "v1"}],
                "runs": 1,
            },
        )

        assert result.output == {"result": "fallback"}
        assert result.experiment_id is None
        assert result.experiment_results is None
