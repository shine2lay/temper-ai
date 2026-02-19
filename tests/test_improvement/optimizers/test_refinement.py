"""Tests for RefinementOptimizer."""

import pytest
from unittest.mock import MagicMock

from temper_ai.improvement._schemas import EvaluationResult
from temper_ai.improvement.optimizers.refinement import RefinementOptimizer


class TestRefinementOptimizer:
    def _make_evaluator(self, results):
        evaluator = MagicMock()
        evaluator.evaluate.side_effect = results
        return evaluator

    def test_first_pass_success(self):
        runner = MagicMock()
        runner.execute.return_value = {"result": "great"}
        evaluator = self._make_evaluator([
            EvaluationResult(passed=True, score=1.0),
        ])
        optimizer = RefinementOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 3}  # noqa
        )

        assert result.output == {"result": "great"}
        assert result.iterations == 0
        assert runner.execute.call_count == 1

    def test_improvement_after_critique(self):
        runner = MagicMock()
        runner.execute.side_effect = [
            {"result": "bad"},
            {"result": "good"},
        ]
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.3),
            EvaluationResult(passed=True, score=0.9),
        ])
        optimizer = RefinementOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 3}  # noqa
        )

        assert result.output == {"result": "good"}
        assert result.score == pytest.approx(0.9)
        assert result.improved is True

    def test_max_iterations_reached(self):
        runner = MagicMock()
        runner.execute.return_value = {"result": "mediocre"}
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.4),
            EvaluationResult(passed=False, score=0.5),
            EvaluationResult(passed=False, score=0.5),
        ])
        optimizer = RefinementOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 2}  # noqa
        )

        assert result.details["final_passed"] is False
        assert result.iterations == 2  # noqa

    def test_with_llm_critique(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "Try harder on quality."
        runner = MagicMock()
        runner.execute.side_effect = [
            {"result": "v1"},
            {"result": "v2"},
        ]
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.3),
            EvaluationResult(passed=True, score=0.8),
        ])
        optimizer = RefinementOptimizer(llm=mock_llm)

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 1}
        )

        assert result.output == {"result": "v2"}
        mock_llm.generate.assert_called_once()

    def test_critique_injected(self):
        runner = MagicMock()
        runner.execute.side_effect = [
            {"result": "v1"},
            {"result": "v2"},
        ]
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.3),
            EvaluationResult(passed=True, score=0.9),
        ])
        optimizer = RefinementOptimizer()

        optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 1}
        )

        # Second call should have critique injected
        second_call_input = runner.execute.call_args_list[1][0][0]
        assert "_optimization_critique" in second_call_input

    def test_with_experiment_service(self):
        mock_service = MagicMock()
        mock_service.create_experiment.return_value = "exp-ref-1"
        mock_service.get_experiment_results.return_value = {
            "recommended_winner": "iteration-1",
            "confidence": 0.88,
        }

        runner = MagicMock()
        runner.execute.side_effect = [
            {"result": "baseline"},
            {"result": "improved"},
        ]
        evaluator = self._make_evaluator([
            EvaluationResult(passed=False, score=0.4),
            EvaluationResult(passed=True, score=0.9),
        ])
        optimizer = RefinementOptimizer(experiment_service=mock_service)

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 2}  # noqa
        )

        assert result.experiment_id == "exp-ref-1"
        assert result.experiment_results is not None
        assert result.output == {"result": "improved"}
        mock_service.create_experiment.assert_called_once()
        mock_service.start_experiment.assert_called_once_with("exp-ref-1")
        # baseline + 1 iteration = 2 assigns
        assert mock_service.assign_variant.call_count == 2  # noqa
        assert mock_service.track_execution_complete.call_count == 2  # noqa
        mock_service.get_experiment_results.assert_called_once_with("exp-ref-1")
        mock_service.stop_experiment.assert_called_once()

    def test_with_experiment_service_first_pass(self):
        """Baseline passes immediately — experiment still tracked."""
        mock_service = MagicMock()
        mock_service.create_experiment.return_value = "exp-ref-2"
        mock_service.get_experiment_results.return_value = {
            "recommended_winner": "baseline",
            "confidence": 1.0,
        }

        runner = MagicMock()
        runner.execute.return_value = {"result": "perfect"}
        evaluator = self._make_evaluator([
            EvaluationResult(passed=True, score=1.0),
        ])
        optimizer = RefinementOptimizer(experiment_service=mock_service)

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 3}  # noqa
        )

        assert result.experiment_id == "exp-ref-2"
        assert result.iterations == 0
        # Only baseline tracked
        assert mock_service.assign_variant.call_count == 1
        assert mock_service.track_execution_complete.call_count == 1
        mock_service.stop_experiment.assert_called_once()

    def test_without_service_no_experiment_fields(self):
        runner = MagicMock()
        runner.execute.return_value = {"result": "ok"}
        evaluator = self._make_evaluator([
            EvaluationResult(passed=True, score=0.9),
        ])
        optimizer = RefinementOptimizer()

        result = optimizer.optimize(
            runner, {"input": "data"}, evaluator, {"max_iterations": 1}
        )

        assert result.experiment_id is None
        assert result.experiment_results is None
