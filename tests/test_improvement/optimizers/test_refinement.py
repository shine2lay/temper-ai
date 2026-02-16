"""Tests for RefinementOptimizer."""

import pytest
from unittest.mock import MagicMock

from src.improvement._schemas import EvaluationResult
from src.improvement.optimizers.refinement import RefinementOptimizer


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
